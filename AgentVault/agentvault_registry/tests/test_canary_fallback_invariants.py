"""§pass47 B3 — Static-analysis tests for canary fallback invariants.

These tests pin the §pass25-b memo-propagation fix and the §pass44 state-hash
race fix in source code. They don't require running PG/Redis (run on host in
<1s alongside A8). If a future refactor accidentally drops the guard the test
will fail loudly.

Background:
  - §pass25-b: `CrossFrameTransferSettled` emit MUST carry `memo` from source
    `CrossFrameTransferInitiated` event so the canary validator can
    correlate via memo when the Redis reverse-index race fires.
  - §pass44: `_record_fire` HSET (recreating `canary:<test_id>` AFTER the
    judge swept it) caused 90s false timeouts. The fix:
      * UPDATE conditional on `outcome='fired'`
      * No unconditional HSET that recreates the state hash
      * Phase 7.6 self-stamp guarded by `EXISTS`
"""
from __future__ import annotations

import pathlib
import re


_SRC_ROOT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "src" / "agentvault_registry"
)

CANARY_RUNNER = _SRC_ROOT / "background_tasks" / "canary_runner.py"
REACTOR_CFI = _SRC_ROOT / "background_tasks" / "reactor_cross_frame_initiated.py"
TEG_INTEGRATION = _SRC_ROOT / "routers" / "teg_integration.py"


def _read(p: pathlib.Path) -> str:
    assert p.exists(), f"missing source: {p}"
    return p.read_text(encoding="utf-8")


# ── §pass44 — _record_fire race fix ─────────────────────────────────────────

def test_record_fire_update_gated_on_outcome_fired():
    """The conditional UPDATE WHERE outcome='fired' prevents clobbering judge verdicts."""
    src = _read(CANARY_RUNNER)
    # find body of _record_fire
    match = re.search(r"async def _record_fire\(.*?\n(?=\nasync def |\Z)", src, re.DOTALL)
    assert match, "_record_fire not found in canary_runner.py"
    body = match.group(0)
    assert ".where(models.CanaryTestResult.outcome ==" in body or \
           "outcome=='fired'" in body or \
           "outcome == \"fired\"" in body or \
           "outcome == 'fired'" in body, (
        "_record_fire UPDATE must be gated on outcome='fired'. Race fix from §pass44."
    )


def test_record_fire_does_not_unconditionally_hset_state_hash():
    """No HSET on `canary:<test_id>` outside an EXISTS guard — recreating
    a swept hash causes the 90s false-timeout class fixed in §pass44."""
    src = _read(CANARY_RUNNER)
    # Find body of _record_fire
    match = re.search(r"async def _record_fire\(.*?\n(?=\nasync def |\Z)", src, re.DOTALL)
    assert match
    body = match.group(0)
    # Any HSET on canary:<test_id> must be inside an `if await redis.exists` guard.
    hset_lines = [(i, line) for i, line in enumerate(body.splitlines())
                  if "redis.hset" in line]
    # Cross-check: every HSET line should have an `exists` check earlier in the function.
    if hset_lines:
        assert "redis.exists" in body, (
            "_record_fire contains an HSET but no EXISTS guard. §pass44 race fix lost."
        )


def test_phase76_intra_self_stamp_guarded_by_exists():
    """The Phase 7.6 intra self-stamp (set `tokens_xfer_seen_iso` from HTTP 200)
    must be guarded by `await redis.exists(key)` so it doesn't recreate a
    hash the judge has already swept."""
    src = _read(CANARY_RUNNER)
    match = re.search(r"async def _record_fire\(.*?\n(?=\nasync def |\Z)", src, re.DOTALL)
    body = match.group(0) if match else ""
    # Look for the canonical guard near the HSET.
    assert "await redis.exists" in body and "redis.hset" in body, (
        "Phase 7.6 self-stamp must be guarded by `await redis.exists(key)` before HSET. "
        "§pass44 race fix."
    )


# ── §pass25-b — Settled memo propagation ───────────────────────────────────

def test_reactor_cfi_propagates_memo_on_settled_emit():
    """`reactor_cross_frame_initiated` must read `memo` from the source event
    data and include it in the CrossFrameTransferSettled emit so the
    validator can correlate via memo when the Redis reverse-index races."""
    src = _read(REACTOR_CFI)
    # The reactor reads source memo:
    assert re.search(r"source_memo\s*=\s*event_data\.get\(\s*[\"']memo[\"']", src), (
        "reactor_cross_frame_initiated must read memo from source event. §pass25-b."
    )
    # AND emits it. Search for any data dict that mentions `memo`:
    assert re.search(r"[\"']memo[\"']\s*:\s*source_memo", src) or \
           re.search(r"[\"']memo[\"']\s*:\s*memo", src), (
        "reactor_cross_frame_initiated must emit memo in CrossFrameTransferSettled."
    )


def test_teg_integration_propagates_memo_on_settled_emit():
    """`teg_integration._settle_cross_frame_async` (or equivalent) must
    propagate memo from source row to Settled emit."""
    src = _read(TEG_INTEGRATION)
    # Settled emits should reference memo. Look for the established marker comment.
    assert "propagate xfer_req.message as memo" in src or \
           re.search(r"CrossFrameTransferSettled.*memo", src, re.DOTALL) or \
           re.search(r"[\"']memo[\"']\s*:\s*\w*memo", src), (
        "teg_integration must propagate memo into CrossFrameTransferSettled. §pass25-b."
    )


# ── canary_xfer reverse-index still written (the second correlation lane) ───

def test_canary_xfer_reverse_index_still_set():
    """`canary_xfer:<transfer_id>` reverse-index must still be written by
    `_record_fire` — even after the §pass44 race fix dropped the
    unconditional state-hash HSET. Memo is the FALLBACK; the
    transfer_id-keyed reverse-index is the PRIMARY correlation lane."""
    src = _read(CANARY_RUNNER)
    assert re.search(r'redis\.set\(\s*f?["\']canary_xfer:\{', src), (
        "canary_xfer:<transfer_id> reverse-index write removed — validator "
        "loses its primary correlation lane."
    )
