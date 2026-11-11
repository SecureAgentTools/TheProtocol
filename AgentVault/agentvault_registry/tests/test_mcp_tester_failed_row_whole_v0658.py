"""V0658 (g), D6-826 2a: the tester history keeps a failed row's whole failure detail.

Before: every stored row's error was cut to 300 characters and its response excerpt to about 2 KB
(routers/mcp_tester.py, the run's slim rows), so a failed federation-suite leg kept the start of its evidence and lost
the rest. The cross-frame chat delivery legs (chat_g1) failed 17 times in 181 runs and none could be settled: the half
of the evidence that reads the host's thread was always past the cut (the V0658 discovery, cluster 2). And V0657's own
pair proof met it again: the settlement legs' archived error stopped mid-word in their evidence.

Now a failed row (not healthy, not skipped) keeps its whole error, and its response excerpt up to 256 KB, a guard
against a pathological payload that says so when it fires. A passing or skipped row is stored as before.
"""
from __future__ import annotations

import json

from agentvault_registry.routers import mcp_tester

LONG = "x" * 5000 + "|the host's thread: still nothing"
BIG = {"evidence": {"host_thread": ["m"] * 4000}}          # about 20 KB as JSON


def _row(healthy, skipped=False, error=LONG, data=BIG):
    return {"name": "federation_suite: chat_g1/delivery", "authRequired": "developer", "healthy": healthy,
            "expected_failure": skipped, "statusCode": 200, "responseData": data, "error": error}


def test_a_failed_row_keeps_its_whole_error():
    r = mcp_tester._slim_row(_row(healthy=False))
    assert r["error"] == LONG and r["error"].endswith("still nothing")


def test_a_failed_row_keeps_its_whole_evidence_up_to_the_guard():
    r = mcp_tester._slim_row(_row(healthy=False))
    assert r["response_excerpt"] == BIG


def test_the_guard_says_when_it_cut():
    huge = {"blob": "y" * (mcp_tester.FAILED_ROW_EXCERPT_MAX + 10)}
    r = mcp_tester._slim_row(_row(healthy=False, data=huge))
    ex = r["response_excerpt"]
    assert ex["_truncated"] is True and ex["_original_bytes"] > mcp_tester.FAILED_ROW_EXCERPT_MAX
    assert len(json.dumps(ex)) < mcp_tester.FAILED_ROW_EXCERPT_MAX + 1024


def test_a_passing_or_skipped_row_is_stored_as_before():
    for row in (_row(healthy=True), _row(healthy=False, skipped=True)):
        r = mcp_tester._slim_row(row)
        assert r["error"] == LONG[:300]
        assert r["response_excerpt"]["_truncated"] is True          # the 2 KB display cap, as before


def test_the_run_builds_its_rows_through_it():
    import inspect
    src = inspect.getsource(mcp_tester)
    assert "slim_results = [_slim_row(rr) for rr in results]" in src
    assert '"error":    (rr.get("error") or "")[:300]' not in src     # the inline cut every row went through
