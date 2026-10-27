"""§VITALS S2b — the hand-rolled worker loops report OUTCOME, not just liveness.

A worker that only stamps a leader TURN proves its loop is moving. It says nothing
about whether the work succeeded, which is precisely the shape that hid
velocity_snapshot: a loop that turned faithfully for the life of the deployment
while every cycle failed.

This is a RATCHET, not a hand-maintained list. The two sets are derived from the
source on every run, so:
  · a converted worker that loses its `vitals.cycle` turns this red;
  · a NEW hand-rolled loop added without one turns this red;
  · and PENDING can only shrink — a file listed there that already has a cycle is
    a stale list, which is the §SANDBOXGATE failure ("a gate with a hand-maintained
    scope passes loudest about the files it cannot see").
"""
from __future__ import annotations

import os
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():                       # image layout: /app/src/agentvault_registry
    SRC = pathlib.Path("/app/src/agentvault_registry")

# Files that own the leadership primitives themselves, not workers.
_INFRA = {"leader.py", "_worker_base.py", "reactor_base.py", "vitals.py"}

# Still liveness-only. This list may only ever SHRINK.
# EMPTY since 2026-09-04: all 32 hand-rolled leader loops now report an outcome.
PENDING: set[str] = set()

# Two of the 32 are SUBSCRIBERS, not periodic cycles (a pubsub listener and a stream
# flusher). Wrapping a subscription that lives for hours in `vitals.cycle` would stamp
# on entry and on exit and say nothing in between, so they stamp on each successful
# leadership RENEWAL instead — which can only happen while their poll loop is still
# turning. They must declare `pattern="subscriber"` to be counted, so the exemption
# cannot be borrowed by a periodic worker that simply skipped the wrapper.
_SUBSCRIBER = 'pattern="subscriber"'


def _scan() -> tuple[set[str], set[str]]:
    """Return (converted, liveness_only) hand-rolled leader loops, from source."""
    converted, pending = set(), set()
    for root in ("background_tasks", "tasks", "services"):
        base = SRC / root
        if not base.is_dir():
            continue
        for dirpath, _, filenames in os.walk(base):
            for name in sorted(filenames):
                if not name.endswith(".py") or ".bak" in name or name in _INFRA:
                    continue
                p = pathlib.Path(dirpath) / name
                s = p.read_text(encoding="utf-8", errors="ignore")
                if "try_acquire_leadership(" not in s:
                    continue
                if "(BackgroundWorker)" in s:     # the base class already stamps
                    continue
                rel = str(p.relative_to(SRC))
                cycles = "vitals.cycle(" in s
                subscribes = "vitals.stamp(" in s and _SUBSCRIBER in s
                (converted if (cycles or subscribes) else pending).add(rel)
    return converted, pending


@pytest.mark.skipif(not SRC.is_dir(), reason="registry source not mounted — gate NOT run")
def test_every_converted_worker_still_reports_its_outcome():
    converted, _ = _scan()
    assert converted, "found no converted workers at all — the scan is broken, not the fleet"
    regressed = PENDING & converted
    assert not regressed, (
        f"these are listed as PENDING but already stamp an outcome — the list is stale: {sorted(regressed)}"
    )


@pytest.mark.skipif(not SRC.is_dir(), reason="registry source not mounted — gate NOT run")
def test_no_new_hand_rolled_loop_arrives_without_a_stamp():
    _, liveness_only = _scan()
    unexpected = liveness_only - PENDING
    assert not unexpected, (
        "new hand-rolled leader loop(s) with no vitals.cycle — a loop that turns while "
        f"every cycle fails looks healthy: {sorted(unexpected)}"
    )


@pytest.mark.skipif(not SRC.is_dir(), reason="registry source not mounted — gate NOT run")
def test_the_ratchet_only_tightens():
    _, liveness_only = _scan()
    assert len(liveness_only) <= len(PENDING), (
        f"liveness-only count grew: {len(liveness_only)} > {len(PENDING)}"
    )
    converted, _ = _scan()
    # The counts are printed so a change is visible in CI output, not just asserted.
    print(f"[§VITALS S2b] hand-rolled loops reporting an outcome: {len(converted)}; "
          f"liveness-only: {len(liveness_only)} (ceiling {len(PENDING)})")


@pytest.mark.skipif(not SRC.is_dir(), reason="registry source not mounted — gate NOT run")
def test_every_return_of_a_pair_returning_worker_returns_a_pair():
    """`_retry_pending` was changed to return (retried, failed) and ONE early return
    still handed back a bare 0. The caller unpacks, so the cycle died with
    `TypeError: cannot unpack non-iterable int object` — caught in production by the
    §VITALS rail within a minute of the deploy, not by any test.

    Checked on the AST: every `return` in the function yields a 2-tuple.
    """
    import ast
    src = (SRC / "background_tasks" / "webhook_retry_worker.py").read_text()
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_retry_pending"]
    assert fn, "_retry_pending not found"
    returns = [n for n in ast.walk(fn[0]) if isinstance(n, ast.Return) and n.value is not None]
    assert returns, "no value-returning statements found — the scan is broken"
    for r in returns:
        assert isinstance(r.value, ast.Tuple) and len(r.value.elts) == 2, (
            f"line {r.lineno}: returns {ast.dump(r.value)[:60]}, caller unpacks a pair"
        )
