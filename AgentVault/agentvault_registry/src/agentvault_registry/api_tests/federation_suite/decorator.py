"""@federation_test decorator + registration.

Tests are registered via the decorator. The runner discovers them by importing
`federation_suite.tests.*` and pulls the registered list from REGISTRY.

Each test gets metadata (name, category, budget_sec, severity, requires) used
by the runner to skip / filter / report.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, MCPError, SANDBOX_REGISTRIES,
    PreconditionUnmet, DeferredCheck,
)
from agentvault_registry.api_tests.probe_meter import (
    record_probe, reset_probes, probe_count, transport_lost_count,
)
from agentvault_registry.api_tests.federation_suite.skip_codes import classify_skip
from agentvault_registry.api_tests.federation_suite import throwaways

logger = logging.getLogger(__name__)


# ─── Test metadata + registry ─────────────────────────────────────────────

@dataclass
class FederationTestSpec:
    """One registered federation test."""
    name: str
    category: str
    budget_sec: float
    severity: str               # "critical" | "high" | "medium" | "low"
    requires: List[str]         # list of registry labels that must exist
    tags: List[str]
    runner: Callable[[FederationTestRig], Awaitable[AssertionResult]]
    # §NIGHTLYTRUTH (2026-09-14): a test that is red BY DESIGN names the finding it waits on. The row
    # stays red (never green by declaration) but is listed apart from the NEW reds, so the twelfth red
    # is visible; the day the finding lands the declaration goes and the row must pass.
    expected_red: Optional[str] = None
    # §SENDEARLY (2026-09-26): the runner starts this test before every other one and, if it returns a
    # DeferredCheck, judges it after all of them. For a test that must wait out the network (a payment to a
    # brand-new agent is parked and re-delivered minutes later) without holding the row to one short budget.
    start_first: bool = False


# Module-level test registry — populated by @federation_test
REGISTRY: List[FederationTestSpec] = []


def federation_test(
    *,
    name: str,
    category: str,
    budget_sec: float = 30.0,
    severity: str = "medium",
    requires: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    expected_red: Optional[str] = None,
    start_first: bool = False,
):
    """Register a federation test.

    The decorated coroutine must accept (rig: FederationTestRig) and return
    an AssertionResult (typically via rig.assert_within).

    Example:
        @federation_test(
            name="broadcast_propagation_mainframe_to_cloudop",
            category="cross_registry_events",
            budget_sec=20.0,
            severity="high",
            requires=["sandbox-A-admin", "sandboxalpha-admin"],
        )
        async def test_broadcast_propagation(rig):
            ...
            return await rig.assert_within(...)
    """
    def _decorator(fn: Callable[[FederationTestRig], Awaitable[AssertionResult]]):
        spec = FederationTestSpec(
            name=name,
            category=category,
            budget_sec=budget_sec,
            severity=severity,
            requires=requires or [],
            tags=tags or [],
            runner=fn,
            expected_red=expected_red,
            start_first=start_first,
        )
        REGISTRY.append(spec)
        return fn
    return _decorator


def silent_legs(state: Any) -> Optional[Tuple[List[str], List[str]]]:
    """§MCPTEST30 (V0549): (silent legs, answered legs) of a state map, or None when no leg is silent.

    116 test files carry a copy of `_is_silent_or_error` (an error text, or an empty answer) and mark such a leg
    {"silent": True}; their predicates accept a silent leg as readily as an answer, so a row whose every leg answered
    an error (a 401 from a wrong credential, a 404 from a retired path, a 503 from a feature that is off) read green.
    A row is judged here, once, rather than in 111 predicates: every leg silent is NOT MEASURED (`unanswered`), some
    legs silent stays a pass that names them."""
    if not isinstance(state, dict) or not state:
        return None
    silent = [str(k) for k, v in state.items() if _leg_is_silent(v)]
    if not silent:
        return None
    return silent, [str(k) for k in state if str(k) not in silent]


def _leg_is_silent(v: Any) -> bool:
    """A leg marked {"silent": True}, or one the test kept as an answer's KEYS where the keys are the admin
    dispatcher's error envelope ({status_code, upstream_error, ...}): the copy-pasted helper reads that dict as an
    answer. Measured on sbx-alpha 2026-10-02 (V0547): cloud_op_self_logs_per_cloudop passed on two such envelopes,
    503 "mainframe only", and no other row of the 112 that accept a silent leg did."""
    if not isinstance(v, dict):
        return False
    if v.get("silent") is True:
        return True
    keys = v.get("keys")
    return isinstance(keys, list) and "upstream_error" in keys


def _legs_only(state: Any) -> Any:
    """What a PASSED outcome keeps of its state (§TWOAGENT, 2026-09-24): the record of which legs ran, as booleans, and
    none of the evidence. Before this a pass carried no state at all, so it could not be audited from its result: a
    reader counting legs met an empty map, and `all()` over nothing reads True. Evidence on every pass would bloat the
    nightly history, and the summary reads `last_state` only from red rows. Flows without a leg map keep None.
    §MCPTEST30 (V0549): a pass with silent legs names them (`silent_legs`), so a partial reading shows on its row."""
    out: Dict[str, Any] = {}
    if isinstance(state, dict) and isinstance(state.get("legs"), dict):
        out = {"legs": {str(k): bool(v) for k, v in state["legs"].items()}, "not_run": list(state.get("not_run") or [])}
    sl = silent_legs(state)
    if sl:
        out["silent_legs"] = sl[0]
    return out or None


@dataclass
class TestOutcome:
    """One test's full outcome including timing breakdown."""
    spec: FederationTestSpec
    state: str                  # "passed"|"failed"|"skipped"|"errored"|"vacuous"
    arrange_ms: int
    act_ms: int
    propagation_ms: int          # for asserts; = AssertionResult.elapsed_sec * 1000
    total_ms: int
    polling_attempts: int = 0
    budget_pct_used: float = 0.0
    skip_reason: Optional[str] = None
    skip_code: Optional[str] = None      # U2 — machine-readable; see skip_codes.py
    probe_count: int = 0                 # U1 — round trips to the system under test
    failure_detail: Optional[str] = None
    last_state: Any = None
    error_repr: Optional[str] = None
    # §SENDEARLY: a start_first test that has acted and waits for its verdict (state "deferred"). Never
    # reported: `finish_deferred` turns it into the row's real outcome before the runner aggregates.
    pending: Optional[DeferredCheck] = None
    # V0641: the agents this test made (throwaways.Made), carried across a deferred check, and what the close did
    # with them once the verdict was in (reported only when it closed or left something; never a verdict)
    made: Any = None
    throwaways: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.spec.name,
            "category": self.spec.category,
            "severity": self.spec.severity,
            "tags": self.spec.tags,
            "budget_sec": self.spec.budget_sec,
            "state": self.state,
            "arrange_ms": self.arrange_ms,
            "act_ms": self.act_ms,
            "propagation_ms": self.propagation_ms,
            "total_ms": self.total_ms,
            "polling_attempts": self.polling_attempts,
            "budget_pct_used": round(self.budget_pct_used, 1),
            "skip_reason": self.skip_reason,
            "skip_code": self.skip_code,
            "probe_count": self.probe_count,
            "failure_detail": self.failure_detail,
            # A transport-lost skip keeps its evidence like a red row (§MCPTEST30): its verdict was not trusted, not absent.
            "last_state": (self.last_state if (self.state == "failed" or self.skip_code in ("transport_lost", "unanswered"))
                           else (_legs_only(self.last_state) if self.state == "passed" else None)),
            "error_repr": self.error_repr,
            "expected_red": self.spec.expected_red,
            **({"throwaways": self.throwaways} if self.throwaways else {}),
        }


# ─── Test execution helper ─────────────────────────────────────────────────

def _transport_lost_outcome(spec: FederationTestSpec, t_start: float, lost: int, verdict: str,
                            detail: Any, last_state: Any = None, polling_attempts: int = 0,
                            budget_pct_used: float = 0.0) -> "TestOutcome":
    """§MCPSWEEP 2026-09-28 (agentvault2-05's proposal): a test during which the transport LOST an answer did not
    measure the product, whatever it returned. A lost answer can read as a refusal (a false pass) as easily as a
    failure (V0481's contract row), and 546 sites in the suite catch Exception broadly, so no per-test rule can tell
    which. The row is NOT MEASURED with what it reported kept in the reason; skip_codes caps how many a run may
    have, so a dead transport cannot turn a run green. (Not applied to a deferred check's later verdict.)

    §MCPTEST30 (2026-09-30): the state the test captured is kept too. Round 2 from EU's console lost one answer during
    the A->B transfer test and its row read only "budget 120.0s exhausted after 9 attempts": the money had moved and
    the settlement event was in the store, and nothing on the row said which condition had not held. The verdict
    stays NOT MEASURED; the evidence behind it is what lets a person look."""
    return TestOutcome(
        spec=spec, state="skipped",
        arrange_ms=0, act_ms=0, propagation_ms=0,
        total_ms=int((time.time() - t_start) * 1000),
        polling_attempts=polling_attempts,
        budget_pct_used=budget_pct_used,
        skip_reason=(f"transport lost: {lost} probe answer(s) were lost in transit during this test (an exec returned "
                     f"rc 0 with no HTTP status marker), so its {verdict} verdict cannot be told from the transport. "
                     f"What it reported: {str(detail or '')[:300]}"),
        skip_code="transport_lost",
        probe_count=probe_count(),
        last_state=last_state,
    )


def _unanswered_outcome(spec: FederationTestSpec, t_start: float, state: str, result: AssertionResult,
                        probes: int) -> Optional["TestOutcome"]:
    """§MCPTEST30 (V0549): a PASS whose every leg was silent measured no answer: NOT MEASURED, code `unanswered`, the
    legs kept as evidence. skip_codes holds the census to a ceiling that may only shrink."""
    sl = silent_legs(result.last_state) if state == "passed" else None
    if not sl or sl[1]:
        return None
    return TestOutcome(
        spec=spec, state="skipped",
        arrange_ms=0, act_ms=0, propagation_ms=int(result.elapsed_sec * 1000),
        total_ms=int((time.time() - t_start) * 1000),
        polling_attempts=result.polling_attempts,
        budget_pct_used=result.budget_pct_used,
        skip_reason=(f"unanswered: every leg answered an error or nothing ({', '.join(sl[0])}); the test accepts "
                     "that as a pass, so the row measured no answer"),
        skip_code="unanswered",
        probe_count=probes,
        last_state=result.last_state,
    )


async def execute_test(spec: FederationTestSpec, rig: FederationTestRig) -> TestOutcome:
    """Run one test, capture timing + outcome, then retire the agents it made (V0641). Never raises."""
    # Skip if required registries aren't in topology map
    for label in spec.requires:
        if label not in SANDBOX_REGISTRIES:
            return TestOutcome(
                spec=spec, state="skipped",
                arrange_ms=0, act_ms=0, propagation_ms=0, total_ms=0,
                skip_reason=f"required registry {label!r} not in topology map",
                skip_code="topology_missing",
            )

    # U1 — zero the probe meter INSIDE this test's Task. asyncio copies the
    # ambient context per Task, so the count that follows belongs to this test
    # alone even under the runner's bounded concurrency. V0641: the list of the agents it makes begins here the same
    # way, and is retired once the verdict is in (a deferred check's after its judgment, in finish_deferred).
    reset_probes()
    run = throwaways.begin(rig)
    outcome = await _run_test(spec, rig)
    if outcome.state == "deferred":
        outcome.made = run
        return outcome
    return await _retire_made(outcome, run)


async def _retire_made(outcome: TestOutcome, run: Any) -> TestOutcome:
    """V0641: what the test made and did not retire itself goes back and is deleted, after its verdict, which the
    close never changes (throwaways.close)."""
    try:
        closed = await throwaways.close(run)
    except Exception as e:                                            # noqa: BLE001 - close never raises; a belt
        closed = {"closed": 0, "left": {"*": [f"the close stopped ({type(e).__name__})"]}}
    if closed.get("closed") or closed.get("left"):
        outcome.throwaways = closed
    return outcome


async def _run_test(spec: FederationTestSpec, rig: FederationTestRig) -> TestOutcome:
    t_start = time.time()
    try:
        result = await spec.runner(rig)
        if isinstance(result, DeferredCheck) and spec.start_first:
            # §SENDEARLY: acted; the verdict comes after every other test (runner.finish_deferred).
            result.started_at = t_start
            return TestOutcome(
                spec=spec, state="deferred",
                arrange_ms=0, act_ms=int((time.time() - t_start) * 1000), propagation_ms=0,
                total_ms=int((time.time() - t_start) * 1000),
                probe_count=probe_count(), pending=result,
            )
        if not isinstance(result, AssertionResult):
            return TestOutcome(
                spec=spec, state="errored",
                arrange_ms=0, act_ms=0, propagation_ms=0,
                total_ms=int((time.time() - t_start) * 1000),
                error_repr=f"test did not return AssertionResult: {type(result).__name__}",
            )
        # Test-internal timing isn't tracked separately yet — we treat the
        # AssertionResult's elapsed as "propagation_ms" and the remainder
        # (start_to_assert_start) as "act_ms". Tests can later report richer
        # timing via custom result fields if needed.
        total_ms = int((time.time() - t_start) * 1000)
        propagation_ms = int(result.elapsed_sec * 1000)
        probes = probe_count()
        # U1 — a test that never reached for the system cannot have measured it.
        # This is a REPORT, not yet a gate: the census in the summary is what
        # earns the right to set a ceiling. `no-probe` declares a test that is
        # structural BY DESIGN (it reads source or config, not the tier).
        if result.passed and probes == 0 and "no-probe" not in spec.tags:
            state = "vacuous"
        else:
            state = "passed" if result.passed else "failed"
        lost = transport_lost_count()
        if lost:
            return _transport_lost_outcome(spec, t_start, lost, state, result.failure_detail or result.description,
                                           last_state=result.last_state, polling_attempts=result.polling_attempts,
                                           budget_pct_used=result.budget_pct_used)
        unanswered = _unanswered_outcome(spec, t_start, state, result, probes)
        if unanswered is not None:
            return unanswered
        return TestOutcome(
            spec=spec,
            state=state,
            probe_count=probes,
            arrange_ms=0,
            act_ms=max(0, total_ms - propagation_ms),
            propagation_ms=propagation_ms,
            total_ms=total_ms,
            polling_attempts=result.polling_attempts,
            budget_pct_used=result.budget_pct_used,
            failure_detail=result.failure_detail,
            last_state=result.last_state,
        )
    except PreconditionUnmet as e:
        # Third state: the fixture this test needs does not exist. Not a red row
        # — a red row here would be a defect report about the environment.
        return TestOutcome(
            spec=spec, state="skipped",
            arrange_ms=0, act_ms=0, propagation_ms=0,
            total_ms=int((time.time() - t_start) * 1000),
            skip_reason=f"precondition unmet: {e}",
            skip_code=classify_skip(str(e)),
            probe_count=probe_count(),
        )
    except MCPError as e:
        lost = transport_lost_count()
        if lost:
            return _transport_lost_outcome(spec, t_start, lost, "errored",
                                           f"MCPError on {e.registry}/{e.tool}: HTTP {e.http_status}: {e.detail[:200]}")
        return TestOutcome(
            spec=spec, state="errored",
            arrange_ms=0, act_ms=0, propagation_ms=0,
            total_ms=int((time.time() - t_start) * 1000),
            error_repr=f"MCPError on {e.registry}/{e.tool}: HTTP {e.http_status}: {e.detail[:200]}",
            probe_count=probe_count(),
        )
    except Exception as e:
        return TestOutcome(
            spec=spec, state="errored",
            arrange_ms=0, act_ms=0, propagation_ms=0,
            total_ms=int((time.time() - t_start) * 1000),
            error_repr=f"{type(e).__name__}: {e!r}",
            probe_count=probe_count(),
        )


async def finish_deferred(outcome: TestOutcome) -> TestOutcome:
    """Judge a start_first test that has acted, then retire the agents it made (V0641). Never raises."""
    throwaways.adopt(outcome.made)
    judged = await _judge_deferred(outcome)
    return await _retire_made(judged, outcome.made)


async def _judge_deferred(outcome: TestOutcome) -> TestOutcome:
    """Judge a start_first test that has acted: await its DeferredCheck and build the row. Never raises.

    §SENDEARLY (2026-09-26). The same three states as `execute_test` (an unmet precondition is a skip, never a red)
    plus the probe meter across both halves: the act ran in its own Task and this runs in another, so the two counts
    are added, or a row that measured everything in its act would read vacuous.
    """
    pending = outcome.pending
    if outcome.state != "deferred" or pending is None:
        return outcome
    spec = outcome.spec
    act_probes = outcome.probe_count
    act_ms = outcome.act_ms
    started = pending.started_at or time.time()
    reset_probes()

    def _row(**kw) -> TestOutcome:
        base = dict(spec=spec, arrange_ms=0, act_ms=act_ms, propagation_ms=0,
                    total_ms=int((time.time() - started) * 1000), probe_count=act_probes + probe_count())
        base.update(kw)
        return TestOutcome(**base)

    try:
        result = await pending.check()
        if not isinstance(result, AssertionResult):
            return _row(state="errored",
                        error_repr=f"deferred check did not return AssertionResult: {type(result).__name__}")
        probes = act_probes + probe_count()
        if result.passed and probes == 0 and "no-probe" not in spec.tags:
            state = "vacuous"
        else:
            state = "passed" if result.passed else "failed"
        return _row(state=state, propagation_ms=int(result.elapsed_sec * 1000),
                    polling_attempts=result.polling_attempts, budget_pct_used=result.budget_pct_used,
                    failure_detail=result.failure_detail, last_state=result.last_state)
    except PreconditionUnmet as e:
        return _row(state="skipped", skip_reason=f"precondition unmet: {e}", skip_code=classify_skip(str(e)))
    except MCPError as e:
        return _row(state="errored",
                    error_repr=f"MCPError on {e.registry}/{e.tool}: HTTP {e.http_status}: {e.detail[:200]}")
    except Exception as e:
        return _row(state="errored", error_repr=f"{type(e).__name__}: {e!r}")
