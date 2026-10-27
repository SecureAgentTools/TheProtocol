"""Federation suite runner — entry point invoked from flow framework.

Discovers all registered tests (by importing federation_suite.tests.*),
runs them sequentially against a FederationTestRig, returns the aggregated
result dict in the BFF-compatible flow shape.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pkgutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agentvault_registry.api_tests.federation_suite.decorator import (
    REGISTRY, TestOutcome, execute_test, finish_deferred,
)
from agentvault_registry.api_tests.federation_suite.reporter import aggregate
from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig
from agentvault_registry.api_tests.probe_meter import self_probe_ok
from agentvault_registry.api_tests.federation_suite.rig import (
    upstream_error_rewrites, reset_upstream_error_rewrites,
)

logger = logging.getLogger(__name__)


def _fed_concurrency(default: int = 4) -> int:
    """Bounded concurrency for the federation test runner (was strictly
    sequential). Tests share one rig (cached MCPClients per registry); most are
    read-only invariant checks, a subset create-then-assert with eventual-
    consistency polls. Conservative default to limit cross-test interference on
    the shared sandbox frames; overlaps the polls + cross-registry latency.
    Override via env MCP_TESTER_FED_CONCURRENCY; =1 forces the legacy sequential
    path (instant rollback via recreate). Re-verify the pass count on change.
    """
    try:
        v = int(os.environ.get("MCP_TESTER_FED_CONCURRENCY", str(default)) or default)
    except (TypeError, ValueError):
        v = default
    return max(1, v)


def _discover_tests() -> int:
    """Import every module under federation_suite.tests to populate REGISTRY.

    Returns the count of registered tests after discovery.
    """
    import agentvault_registry.api_tests.federation_suite.tests as tests_pkg
    pre = len(REGISTRY)
    for _, name, _ in pkgutil.iter_modules(tests_pkg.__path__):
        try:
            importlib.import_module(
                f"agentvault_registry.api_tests.federation_suite.tests.{name}"
            )
        except Exception as e:
            logger.warning(
                f"[FederationSuite] failed to import test module {name!r}: {e!r}"
            )
    post = len(REGISTRY)
    logger.info(f"[FederationSuite] discovered {post - pre} new tests "
                f"(total registered: {post})")
    return post


async def _preflight_credentials(rig, candidates) -> Optional[Dict[str, Any]]:
    """Authenticate once against every registry the selected tests require.

    Returns None when every login succeeds; otherwise a flow-result dict that
    names each unusable registry -- label, container, admin email and the env
    var that supplies its password -- so the failure is a config sentence rather
    than several hundred budget timeouts.
    """
    from .rig import SANDBOX_REGISTRIES

    labels = sorted({lbl for spec in candidates for lbl in (getattr(spec, "requires", None) or [])
                     if lbl in SANDBOX_REGISTRIES})
    if not labels:
        return None

    broken: List[Dict[str, str]] = []
    for label in labels:
        try:
            await rig.mcp(label)._ensure_jwt()
        except Exception as e:                                     # noqa: BLE001
            rspec = SANDBOX_REGISTRIES[label]
            broken.append({
                "label": label,
                "container": rspec.container,
                "admin_email": rspec.admin_email,
                "password_env": rspec.password_env or "(unset: falls back to the shared SANDBOX_ADMIN_PASSWORD)",
                "error": str(e)[:180],
            })
    if not broken:
        logger.info("[FederationSuite] credential preflight OK for %d registry/ies: %s",
                    len(labels), ", ".join(labels))
        return None

    detail = "; ".join(
        "%s -> container=%s email=%s password_env=%s" %
        (b["label"], b["container"], b["admin_email"], b["password_env"]) for b in broken)
    logger.error("[FederationSuite] credential preflight FAILED: %s", detail)
    return {
        "flow_name": "flow_federation_suite_complete",
        "success": False,
        "total_steps": len(candidates),
        "successful_steps": 0,
        "error": ("credential preflight failed for %d of %d registry/ies -- suite NOT run. %s"
                  % (len(broken), len(labels), detail)),
        "results": [],
        "flow_values": {
            "summary": {"total": len(candidates), "passed": 0, "failed": 0,
                        "skipped": len(candidates), "errored": 0, "vacuous": 0,
                        "pass_pct": 0.0, "skip_census": {"credential_preflight_failed": len(candidates)},
                        "skips_ok": False,
                        "skip_complaints": ["credential preflight failed -- see broken_registries"]},
            "candidate_count": len(candidates),
            "registered_total": len(REGISTRY),
            "broken_registries": broken,
        },
    }


async def execute_all(candidates, rig, concurrency: int) -> List[TestOutcome]:
    """Run the candidates and return their outcomes in candidate order.

    Bounded-parallel execution (was strictly sequential). Tests share one rig;
    moderate concurrency overlaps eventual-consistency polls + cross-registry
    latency. =1 reverts to sequential. Re-verify the pass count after changing.

    §SENDEARLY (2026-09-26, his words "fix the test so the transfer goes out at the beginning of the test run and
    success is measured later in the test run"): a `start_first` test starts before every other one and outside the
    concurrency bound (its act is a few calls and a wait, and a bound of 1 must not put it behind the whole suite).
    If it returns a DeferredCheck, that check runs after EVERY other test has finished and decides the row.
    """
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    done = 0
    total = len(candidates)

    def _log(spec, outcome):
        logger.info(
            f"[FederationSuite] [{done}/{total}] "
            f"{spec.category}/{spec.name} → {outcome.state.upper()} "
            f"(elapsed {outcome.total_ms}ms, attempts {outcome.polling_attempts})"
        )

    async def _run_one_fed(idx, spec):
        nonlocal done
        async with sem:
            outcome = await execute_test(spec, rig)
        done += 1
        _log(spec, outcome)
        return idx, outcome

    async def _act_first(idx, spec):
        return idx, await execute_test(spec, rig)

    async def _verdict(idx, outcome):
        nonlocal done
        if outcome.state == "deferred":
            logger.info(f"[FederationSuite] {outcome.spec.category}/{outcome.spec.name}: judging the act "
                        f"that started the run")
            outcome = await finish_deferred(outcome)
        done += 1
        _log(outcome.spec, outcome)
        return idx, outcome

    first = [(i, sp) for i, sp in enumerate(candidates) if getattr(sp, "start_first", False)]
    rest = [(i, sp) for i, sp in enumerate(candidates) if not getattr(sp, "start_first", False)]
    # created (and so scheduled) before any bounded test is: they run first
    acting = [asyncio.create_task(_act_first(i, sp)) for i, sp in first]
    pairs = list(await asyncio.gather(*[_run_one_fed(i, sp) for i, sp in rest]))
    acted = await asyncio.gather(*acting)
    pairs += list(await asyncio.gather(*[_verdict(i, o) for i, o in acted]))
    pairs.sort(key=lambda p: p[0])
    return [o for _i, o in pairs]


async def run_federation_suite(
    *,
    category_filter: Optional[List[str]] = None,
    severity_filter: Optional[List[str]] = None,
    test_name_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run every registered federation test (filtered) and return a
    BFF-compatible flow result.

    Args:
      category_filter: only run tests whose category is in this list
      severity_filter: only run tests whose severity is in this list
      test_name_filter: only run tests whose name is in this list

    Returns:
      A dict matching the APITestBase flow shape, plus a `flow_values.summary`
      block with aggregated stats from `reporter.aggregate`.
    """
    _discover_tests()

    # Apply filters
    candidates = list(REGISTRY)
    if category_filter:
        candidates = [s for s in candidates if s.category in category_filter]
    if severity_filter:
        candidates = [s for s in candidates if s.severity in severity_filter]
    if test_name_filter:
        candidates = [s for s in candidates if s.name in test_name_filter]

    if not candidates:
        return {
            "flow_name": "flow_federation_suite_complete",
            "success": False,
            "total_steps": 0,
            "successful_steps": 0,
            "error": "no tests matched filters (or no tests registered)",
            "results": [],
            "flow_values": {
                "summary": {
                    "total": 0, "passed": 0, "failed": 0, "skipped": 0, "errored": 0,
                    "vacuous": 0, "pass_pct": 0.0, "skip_census": {},
                    "skips_ok": True, "skip_complaints": [],
                },
                "candidate_count": 0,
                "registered_total": len(REGISTRY),
            },
        }

    logger.info(
        f"[FederationSuite] running {len(candidates)} test(s) "
        f"(filter: category={category_filter}, severity={severity_filter}, "
        f"name={test_name_filter})"
    )

    rig = FederationTestRig()

    # ── §EVTYPES 2026-09-05: credential preflight ─────────────────────────────
    # Every registry this run will dial must authenticate BEFORE any test runs.
    # Without this, a single mis-paired credential is invisible: each test dials,
    # 401s, retries until its budget is spent, and reports "budget 15.0s exhausted
    # after 10 attempts" -- naming a timeout, never a login. Measured 2026-09-05:
    # 403 of 557 rows failed that way, ~10 minutes of wall clock, and the real
    # cause (frame A pinned to the other frame's admin) appeared in NO row's error.
    # One login per distinct registry: cheap, and it turns that into one sentence.
    preflight = await _preflight_credentials(rig, candidates)
    if preflight is not None:
        return preflight

    reset_upstream_error_rewrites()
    t_start = time.time()

    outcomes = await execute_all(candidates, rig, _fed_concurrency())

    wall_s = time.time() - t_start
    summary = aggregate(outcomes)

    # U1 — a zero probe count is a claim about the METER until the meter has
    # been seen to count. Ask it directly, and publish the answer beside the
    # census so a reader never has to trust an unproven instrument.
    # ⚠ Publish how often the B6 compatibility shim had to rebuild a flattened
    # envelope. Non-zero means the dispatcher bug is still live upstream and
    # this suite is only green because it works around it — say so on screen
    # rather than let a shim quietly launder someone else's regression.
    summary["upstream_error_rewrites"] = upstream_error_rewrites()
    meter_ok = self_probe_ok()
    summary["probe_meter_self_test"] = "counts" if meter_ok else "BROKEN"
    if not meter_ok:
        summary["vacuous_tests"] = []
        summary["probe_stats"]["note"] = (
            "probe meter self-test FAILED — every vacuity verdict in this run is "
            "unproven and has been withheld rather than reported as fact"
        )
        logger.error("[FederationSuite] probe meter self-test FAILED — "
                     "vacuity verdicts withheld")
    logger.info(
        f"[FederationSuite] probes={summary['probe_stats']['total_probes']} "
        f"meter={summary['probe_meter_self_test']} "
        f"vacuous={summary.get('vacuous', 0)} "
        f"skip_census={summary.get('skip_census')}"
    )
    for complaint in summary.get("skip_complaints", []):
        logger.warning(f"[FederationSuite] SKIP GATE: {complaint}")

    # Format outcomes into APITestBase results shape
    results = []
    for o in outcomes:
        results.append({
            "step": len(results) + 1,
            "name": f"federation_suite: {o.spec.category}/{o.spec.name}",
            "path": "/admin/api-test/test-flow",
            "method": "POST",
            "authRequired": "developer",
            "healthy": o.state == "passed",
            "statusCode": 200 if o.state in ("passed", "failed") else 0,
            "responseData": o.to_dict(),
            "error": o.failure_detail or o.error_repr,
            "expected_failure": o.state == "skipped",
            "expected_red": o.spec.expected_red,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "flow_name": "flow_federation_suite_complete",
        # U2 — the skip gate is part of the verdict. A suite whose tests quietly
        # stop running is not a passing suite; that is how two live defects hid.
        # Vacuity is REPORTED but deliberately not gating yet — the census from
        # the first real run is what earns a ceiling.
        "success": (summary["failed"] == 0 and summary["errored"] == 0
                    and summary.get("skips_ok", True)),
        "total_steps": len(outcomes),
        "successful_steps": summary["passed"],
        "error": None,
        "results": results,
        "flow_values": {
            "summary": summary,
            "candidate_count": len(candidates),
            "registered_total": len(REGISTRY),
            "wall_s": round(wall_s, 1),
        },
    }
