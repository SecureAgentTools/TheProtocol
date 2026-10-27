"""Federation suite reporter — outcome aggregation + per-suite stats."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from agentvault_registry.api_tests.federation_suite.decorator import TestOutcome
from agentvault_registry.api_tests.federation_suite.skip_codes import (
    classify_skip, code_meanings, skip_verdict, UNCLASSIFIED,
)


STATES = ("passed", "failed", "skipped", "errored", "vacuous")


def _percentile(values: List[int], pct: float) -> int:
    if not values:
        return 0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * pct / 100.0)
    return sorted_v[min(idx, len(sorted_v) - 1)]


def aggregate(outcomes: List[TestOutcome]) -> Dict[str, Any]:
    """Produce per-suite summary stats from a list of TestOutcome."""
    total = len(outcomes)
    by_state = Counter(o.state for o in outcomes)
    passed = by_state["passed"]
    failed = by_state["failed"]
    skipped = by_state["skipped"]
    errored = by_state["errored"]
    vacuous = by_state["vacuous"]

    # Per-category breakdown
    # ⚠ These per-state dicts used to be written out by hand, which meant a new
    # state (U1's "vacuous") raised KeyError deep inside aggregation rather than
    # showing up as a number. Derive the keys from STATES so adding a state is
    # one edit, not a hunt.
    by_category: Dict[str, Dict[str, int]] = {}
    for o in outcomes:
        cat = o.spec.category
        c = by_category.setdefault(cat, {"total": 0, **{k: 0 for k in STATES}})
        c["total"] += 1
        c[o.state] = c.get(o.state, 0) + 1

    # Per-severity breakdown
    by_severity: Dict[str, Dict[str, int]] = {}
    for o in outcomes:
        sev = o.spec.severity
        d = by_severity.setdefault(sev, {"total": 0, **{k: 0 for k in STATES}})
        d["total"] += 1
        d[o.state] = d.get(o.state, 0) + 1

    # Propagation latency stats (passed tests only, per category)
    prop_by_cat: Dict[str, List[int]] = {}
    for o in outcomes:
        if o.state == "passed":
            prop_by_cat.setdefault(o.spec.category, []).append(o.propagation_ms)
    latency_stats: Dict[str, Dict[str, int]] = {}
    for cat, vals in prop_by_cat.items():
        latency_stats[cat] = {
            "n": len(vals),
            "p50_ms": _percentile(vals, 50),
            "p95_ms": _percentile(vals, 95),
            "p99_ms": _percentile(vals, 99),
            "max_ms": max(vals),
            "min_ms": min(vals),
        }

    # Budget violations — passed but used >80% of budget (early warning)
    budget_violations = [
        {"name": o.spec.name, "budget_pct_used": o.budget_pct_used, "budget_sec": o.spec.budget_sec}
        for o in outcomes if o.state == "passed" and o.budget_pct_used > 80.0
    ]

    # Failed tests detail (for quick triage)
    failures = [
        {
            "name": o.spec.name,
            "category": o.spec.category,
            "severity": o.spec.severity,
            "failure_detail": o.failure_detail or o.error_repr,
            "polling_attempts": o.polling_attempts,
            "elapsed_ms": o.total_ms,
        }
        for o in outcomes if o.state in ("failed", "errored")
    ]

    # ── U2: skip census. Free text cannot be gated; a code can. ──────────
    skip_census: Dict[str, int] = {}
    unread_skips: List[Dict[str, str]] = []
    for o in outcomes:
        if o.state != "skipped":
            continue
        code = o.skip_code or classify_skip(o.skip_reason or "")
        skip_census[code] = skip_census.get(code, 0) + 1
        if code == UNCLASSIFIED:
            unread_skips.append({"name": o.spec.name, "reason": (o.skip_reason or "")[:300]})
    skips_ok, skip_complaints = skip_verdict(skip_census)

    # ── U1: vacuity. A pass with zero probes measured nothing. ───────────
    vacuous_tests = [
        {"name": o.spec.name, "category": o.spec.category, "severity": o.spec.severity}
        for o in outcomes if o.state == "vacuous"
    ]
    probe_counts = [o.probe_count for o in outcomes if o.state in ("passed", "vacuous")]
    probe_stats = {
        "total_probes": sum(o.probe_count for o in outcomes),
        "min_on_pass": min(probe_counts) if probe_counts else 0,
        "p50_on_pass": _percentile(probe_counts, 50),
        "max_on_pass": max(probe_counts) if probe_counts else 0,
        "declared_no_probe": sum(1 for o in outcomes if "no-probe" in o.spec.tags),
    }

    pass_pct = (passed * 100.0 / total) if total else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errored": errored,
        "vacuous": vacuous,
        "pass_pct": round(pass_pct, 2),
        "skip_census": skip_census,
        "skip_code_meanings": code_meanings(),
        "skips_ok": skips_ok,
        "skip_complaints": skip_complaints,
        "unread_skips": unread_skips,
        "vacuous_tests": vacuous_tests,
        "probe_stats": probe_stats,
        "by_category": by_category,
        "by_severity": by_severity,
        "latency_stats": latency_stats,
        "budget_violations": budget_violations,
        "failures": failures,
        "total_wall_ms": sum(o.total_ms for o in outcomes),
    }
