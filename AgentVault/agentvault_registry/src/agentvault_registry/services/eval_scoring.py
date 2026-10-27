"""Deterministic scorers for Agent Evals v1 (no LLM-judge — that's v2).

Each scorer maps (task, observed) → (score in [0,1], passed bool). Kept pure and
dependency-free so it unit-tests without the app or a DB.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


def score_task(
    scorer: str,
    expected: Optional[Dict[str, Any]],
    *,
    status_code: Optional[int],
    body: Optional[str],
    latency_ms: Optional[int],
    quorum_score: Optional[float] = None,
) -> Tuple[float, bool]:
    """Return (score, passed). Never raises — an unknown scorer scores 0.

    ``quorum_score`` (GÖDEL FORGE) — for the ``code_patch`` scorer, the fraction of held-out
    hidden tests that passed, as settled by the N-of-M verifier quorum (never self-reported)."""
    expected = expected or {}
    body = body or ""

    if scorer == "code_patch":
        # GÖDEL FORGE — objective code benchmark. Score = quorum-settled fraction of held-out
        # tests passed; passed = score ≥ pass_threshold (default 1.0 = all hidden tests green).
        # No quorum verdict yet → 0/False (never trust a self-reported score).
        if quorum_score is None:
            return (0.0, False)
        s = max(0.0, min(1.0, float(quorum_score)))
        thr = float(expected.get("pass_threshold", 1.0))
        return (s, s >= thr)

    if scorer == "status_ok":
        ok = status_code is not None and 200 <= status_code < 300
        return (1.0 if ok else 0.0, ok)

    if scorer == "exact":
        want = str(expected.get("value", ""))
        ok = body.strip() == want.strip()
        return (1.0 if ok else 0.0, ok)

    if scorer == "contains":
        want = str(expected.get("value", ""))
        ok = want in body
        return (1.0 if ok else 0.0, ok)

    if scorer == "regex":
        pattern = str(expected.get("value", ""))
        try:
            ok = re.search(pattern, body) is not None
        except re.error:
            return (0.0, False)
        return (1.0 if ok else 0.0, ok)

    if scorer == "latency_under_ms":
        threshold = expected.get("value")
        if latency_ms is None or threshold is None:
            return (0.0, False)
        ok = latency_ms <= float(threshold)
        # Graded: full marks well under threshold, tapering to 0 as it approaches the limit.
        # (Bug fix 2026-07-19: previously returned `1.0 if ok else score`, which discarded the
        # graded value and made every passing task score a flat 1.0 — the graded branch was dead.)
        score = max(0.0, min(1.0, 1.0 - (latency_ms / float(threshold)))) if ok else 0.0
        return (score, ok)

    return (0.0, False)


def aggregate(results: list[Tuple[float, float]]) -> float:
    """Weighted mean of (score, weight) pairs → suite score in [0,1]."""
    total_w = sum(w for _, w in results)
    if total_w <= 0:
        return 0.0
    return sum(s * w for s, w in results) / total_w
