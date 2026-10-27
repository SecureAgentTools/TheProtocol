"""Canary judge — sweeps in-flight canary test state and rules pass/fail.

Periodic leader-elected task. Every cycle:
  1. SCAN Redis for canary:* keys (in-flight canary tests).
  2. For each test:
     a. Read the hash (set by canary_runner + filled by reactor_canary_validator).
     b. If all expected events seen → outcome='passed', stamp completed_at,
        compute total_latency_ms.
     c. Else if elapsed > slo_settled_sec + grace → outcome='failed' (timeout).
     d. Else: still in flight, leave for next cycle.
  3. Persist final outcome to canary_test_results.
  4. Update canary_path_health Prom gauge + emit canary_transfer_total counter.
  5. Delete Redis hash + reverse-indexes.

Self-gates via CANARY_JUDGE_ENABLED (default OFF — only registry-a sets to true,
since canary_test_results lives there).
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import select, update

from .. import models
from ..database import get_db_context
from ._worker_base import BackgroundWorker
from .leader import get_redis, try_acquire_leadership

logger = logging.getLogger(__name__)


CANARY_ENABLED = os.environ.get("CANARY_ENABLED", "true").lower() == "true"
CANARY_JUDGE_ENABLED = os.environ.get("CANARY_JUDGE_ENABLED", "false").lower() == "true"
# §CANARYBIND: shared runtime pause key (owned by canary_runner) — imported so the
# scheduler, the judge and the rebalancer can never disagree about "paused".
from .canary_runner import CANARY_FLEET_PAUSED_KEY  # noqa: E402
CANARY_JUDGE_INTERVAL_SEC = int(os.environ.get("CANARY_JUDGE_INTERVAL_SEC", "5"))
CANARY_JUDGE_TIMEOUT_GRACE = int(os.environ.get("CANARY_JUDGE_TIMEOUT_GRACE", "30"))
CANARY_JUDGE_LEADER_KEY = os.environ.get("CANARY_JUDGE_LEADER_KEY", "canary_judge")
CANARY_JUDGE_SCAN_BATCH = int(os.environ.get("CANARY_JUDGE_SCAN_BATCH", "200"))


# Prometheus metrics (best-effort)
try:
    from prometheus_client import Counter as _JCounter, Gauge as _JGauge

    CANARY_TRANSFER_TOTAL = _JCounter(
        "canary_transfer_total",
        "Canary transfers by path/backend/outcome",
        labelnames=["path", "backend", "outcome"],
    )
    CANARY_PATH_HEALTH = _JGauge(
        "canary_path_health",
        "1=last test passed, 0=last test failed",
        labelnames=["path", "backend"],
    )
    CANARY_PENDING = _JGauge(
        "canary_transfer_pending",
        "In-flight canary tests by path",
        labelnames=["path", "backend"],
    )
except Exception:  # pragma: no cover
    CANARY_TRANSFER_TOTAL = None
    CANARY_PATH_HEALTH = None
    CANARY_PENDING = None


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _decode(value):
    if isinstance(value, (bytes, bytearray)):
        return value.decode()
    return value


def _expected_seen(state: dict) -> tuple[bool, list[str]]:
    """Return (all_seen, missing_fields) for the given canary state hash.

    For backend='intra' (sender+receiver on SAME registry — not currently used
    in production canary matrix): expect tokens_xfer + fee_collected.

    For backend='async' (cross-registry, async path): require cf_initiated +
    cf_settled. TokensTransferred and TransactionFeeCollected are recorded as
    informational when they happen to correlate (e.g., registry-a is its own
    TEG host) but their transaction_ids differ from the cross-registry
    transfer_id so reverse-index miss is expected.

    For backend='2pc' (cross-registry, two-phase commit path): the synchronous
    2pc dispatcher emits TokensTransferred + TransactionFeeCollected (via
    `_emit_cross_registry_events`) — no CrossFrameTransferInitiated/Settled.
    Treat 2pc the same as 'intra' from a validator-event perspective.
    """
    backend = state.get("backend", "")
    # §FX (2026-06-03): cross-currency FX swaps emit ONLY FxSwapSettled — no
    # CrossFrame*/TokensTransferred event correlatable to the swap_id — and that
    # audit event is NOT cross-frame-replicated to the hub (not in the ES
    # CROSS_FRAME_BROADCAST_TYPES allowlist), so async ES-event validation can
    # never see it (least of all the reverse C→A leg, whose event lives only on
    # Frame-C's ES). The canary_runner self-stamps fx_settled_seen_iso from the
    # SYNCHRONOUS cross-registry-transfer response (the FX booth is synchronous /
    # source-orchestrated); its presence is authoritative proof the swap settled.
    # A refund sets fx_refunded_seen_iso + failure_signal (see _is_failure).
    if state.get("fx_settled_seen_iso"):
        return (True, [])
    if backend == "intra":
        # Phase 7.6 (2026-05-04): /teg/transfer emits BOTH TokensTransferred AND
        # TransactionFeeCollected with matching transaction_id, but the fee event
        # has no `memo` field (only TT does), so the validator's memo fallback
        # only catches TT. The `canary_xfer:<tx_id>` reverse-index is written by
        # the runner AFTER HTTP response — by then both events have already been
        # WS-broadcast and the fee event was missed. TokensTransferred is the
        # canonical proof of value transfer; the fee event still emits to ES for
        # audit but the canary judge gates only on TT (mirrors 2pc logic).
        required = ["tokens_xfer_seen_iso"]
        missing = [f for f in required if not state.get(f)]
        return (len(missing) == 0, missing)
    if backend == "2pc":
        # 2pc emits TokensTransferred (memo `cross_registry:canary-<test_id>`)
        # locally on the SENDER's frame ES; for cross-frame 2pc the dispatcher
        # ADDITIONALLY emits CrossFrameTransferSettled (Phase 7.5, 2026-05-04)
        # which SF-4 broadcasts to the receiver frame's WS. Either signal
        # proves the transfer landed:
        #   - intra-frame 2pc: tokens_xfer_seen_iso (TT on local ES)
        #   - cross-frame 2pc, sender on judge's frame: tokens_xfer + cf_settled_local
        #   - cross-frame 2pc, sender on OTHER frame: cf_settled_remote (replicated)
        if state.get("tokens_xfer_seen_iso"):
            return (True, [])
        if state.get("cf_settled_local_seen_iso") or state.get("cf_settled_remote_seen_iso"):
            return (True, [])
        return (False, ["tokens_xfer_seen_iso OR cf_settled_(local|remote)_seen_iso"])
    # Cross-registry async: only Initiated + Settled are required.
    # Settled may arrive as cf_settled_local (sender frame emits) OR
    # cf_settled_remote (receiver frame emits + SF-4 replicates).
    missing = []
    if not state.get("cf_initiated_seen_iso"):
        missing.append("cf_initiated_seen_iso")
    if not (state.get("cf_settled_local_seen_iso") or state.get("cf_settled_remote_seen_iso")):
        missing.append("cf_settled_(local|remote)_seen_iso")
    return (len(missing) == 0, missing)


def _is_failure(state: dict) -> Optional[str]:
    """Return failure-type string if state indicates an explicit failure."""
    if (state.get("cf_refunded_seen_iso")
            or state.get("fx_refunded_seen_iso")
            or state.get("failure_signal") == "refunded"):
        return "refunded"
    return None


async def _judge_one(
    redis,
    db,
    test_key: str,
    state: dict,
    slo_settled_sec_default: int = 60,
) -> Optional[str]:
    """Decide a single canary test's outcome and persist. Returns outcome or None."""
    test_id = state.get("test_id") or test_key.split(":", 1)[-1]
    path_human = state.get("path_human", "")
    backend = state.get("backend", "")
    fired_iso = state.get("fired_iso", "")
    if not fired_iso:
        return None

    try:
        fired_at = datetime.datetime.fromisoformat(fired_iso)
    except Exception:
        return None

    # Decide outcome
    failure = _is_failure(state)
    all_seen, missing = _expected_seen(state)
    elapsed = (_now_utc() - fired_at).total_seconds()

    # Look up path config for SLO
    path_id_str = state.get("path_id", "")
    slo_settled_sec = slo_settled_sec_default
    try:
        if path_id_str:
            r = await db.execute(
                select(models.CanaryPath.slo_settled_sec).where(
                    models.CanaryPath.id == int(path_id_str)
                )
            )
            v = r.scalar_one_or_none()
            if v:
                slo_settled_sec = int(v)
    except Exception:
        pass

    deadline = slo_settled_sec + CANARY_JUDGE_TIMEOUT_GRACE
    outcome: Optional[str] = None
    failure_type: Optional[str] = None
    failure_detail: Optional[dict] = None

    if failure:
        outcome = "failed"
        failure_type = failure
        failure_detail = {"reason": "saga_refunded", "elapsed_sec": elapsed}
    elif all_seen:
        outcome = "passed"
    elif elapsed > deadline:
        outcome = "failed"
        failure_type = "timeout"
        failure_detail = {
            "reason": "slo_window_exceeded",
            "elapsed_sec": elapsed,
            "slo_settled_sec": slo_settled_sec,
            "missing_events": missing,
        }
    else:
        return None  # still in flight

    # Compute latency
    # 2026-05-04: total_latency_ms reflects ACTUAL settle time (latest expected
    # event seen) instead of judge-sweep wallclock. Without this, latency was
    # dominated by `CANARY_JUDGE_INTERVAL_SEC` (30s default → 15s avg wait), making
    # the metric useless for measuring real cross-frame transfer performance.
    completed_at = _now_utc()
    last_seen_at = completed_at
    if outcome == "passed":
        if backend == "intra":
            # Phase 7.6: only tokens_xfer is reliably correlatable for intra.
            # fee_collected_seen_iso may also be set if the timing wins (rare),
            # so include it opportunistically — max() picks latest.
            seen_iso_keys = ["tokens_xfer_seen_iso", "fee_collected_seen_iso"]
        elif backend == "2pc":
            # Phase 7.5: include both signals — whichever arrived first wins
            # for latency. Cross-frame 2pc has cf_settled_remote_seen_iso via
            # SF-4 broadcast; intra-frame 2pc only has tokens_xfer_seen_iso.
            seen_iso_keys = [
                "tokens_xfer_seen_iso",
                "cf_settled_local_seen_iso",
                "cf_settled_remote_seen_iso",
            ]
        else:
            # async: cf_initiated + (cf_settled_local OR cf_settled_remote);
            # FX swaps settle synchronously and carry fx_settled_seen_iso.
            seen_iso_keys = [
                "cf_initiated_seen_iso",
                "cf_settled_local_seen_iso",
                "cf_settled_remote_seen_iso",
                "fx_settled_seen_iso",
            ]
        seen_isos = [state.get(k) for k in seen_iso_keys if state.get(k)]
        if seen_isos:
            try:
                last_seen_at = max(
                    datetime.datetime.fromisoformat(v) for v in seen_isos
                )
            except Exception:
                pass
    total_latency_ms = int((last_seen_at - fired_at).total_seconds() * 1000)

    # Persist outcome to canary_test_results
    try:
        await db.execute(
            update(models.CanaryTestResult)
            .where(models.CanaryTestResult.test_id == test_id)
            .values(
                outcome=outcome,
                completed_at=completed_at,
                total_latency_ms=total_latency_ms,
                failure_type=failure_type,
                failure_detail=failure_detail,
            )
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"[CanaryJudge] DB update failed for {test_id}: {e}")

    # Prom metrics
    if CANARY_TRANSFER_TOTAL is not None:
        try:
            CANARY_TRANSFER_TOTAL.labels(
                path=path_human, backend=backend, outcome=outcome
            ).inc()
        except Exception:
            pass
    if CANARY_PATH_HEALTH is not None:
        try:
            CANARY_PATH_HEALTH.labels(path=path_human, backend=backend).set(
                1 if outcome == "passed" else 0
            )
        except Exception:
            pass

    # Cleanup Redis state
    try:
        tid = state.get("transfer_id")
        if tid:
            await redis.delete(f"canary_xfer:{tid}")
        await redis.delete(f"canary_corr:{test_id}")
        await redis.delete(test_key)
    except Exception:
        pass

    logger.info(
        f"[CanaryJudge] {test_id} → {outcome} (path={path_human} backend={backend} "
        f"latency={total_latency_ms}ms failure={failure_type or '-'})"
    )
    return outcome


# §CANARYGAUGE (2026-08-05) — keys that live in the `canary:` namespace but are NOT
# in-flight test state. The scan in _judge_cycle counts everything it cannot resolve
# to an outcome as a PENDING TEST, so a bookkeeping key is reported as a permanently
# stuck canary: `canary:last_fire` (the scheduler's fire watermark) is a HASH, so
# `hgetall` returns non-empty and it survived every guard — it was the standing +1 in
# `[CanaryJudge] … pending=N` and in the `canary_transfer_pending` gauge.
# `canary:ironhand:*` escaped the count only BY ACCIDENT: it is a LIST, `hgetall`
# raises WRONGTYPE, and the bare `except: continue` below swallowed it. Accidental
# correctness is not correctness — name both explicitly.
#
# Why it matters beyond tidiness: a gauge pinned at a constant cannot show a REAL
# pending buildup, which is the one thing it exists to show (same class as the
# §JITTER lesson — never trust a count from an instrument you have not sanity-checked).
_NON_TEST_CANARY_KEYS = frozenset({"canary:last_fire"})
_NON_TEST_CANARY_PREFIXES = ("canary_xfer:", "canary_corr:", "canary:ironhand:")


async def _judge_cycle() -> None:
    if not (CANARY_ENABLED and CANARY_JUDGE_ENABLED):
        return
    redis = await get_redis()
    if redis is None:
        return
    # §CANARYBIND 2026-08-08 (Commander): the judge only ever adjudicates canary
    # tests, so a paused fleet leaves it scanning for work that cannot arrive
    # (measured post-pause on registry-a: `[CanaryJudge] cycle done: judged=0
    # pending=3` every ~5 s). Honour the SAME runtime key the runner does, so one
    # pause call quiets all three workers without a recreate. Per-cycle, so
    # resume is equally instant.
    try:
        if await redis.get(CANARY_FLEET_PAUSED_KEY):
            return
    except Exception:
        pass

    # Scan + judge each in-flight test
    cursor = 0
    judged = 0
    pending = 0
    pending_per_path: dict[tuple[str, str], int] = {}
    async with get_db_context() as db:
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor, match="canary:*", count=CANARY_JUDGE_SCAN_BATCH
            )
            for raw_key in keys:
                key = _decode(raw_key)
                # Skip index keys and non-test bookkeeping/metric keys — see
                # _NON_TEST_CANARY_* above for why each one is named.
                if (
                    not key.startswith("canary:")
                    or key in _NON_TEST_CANARY_KEYS
                    or key.startswith(_NON_TEST_CANARY_PREFIXES)
                ):
                    continue
                try:
                    state_raw = await redis.hgetall(key)
                except Exception:
                    continue
                state = {_decode(k): _decode(v) for k, v in (state_raw or {}).items()}
                if not state:
                    continue
                outcome = await _judge_one(redis, db, key, state)
                if outcome is not None:
                    judged += 1
                else:
                    pending += 1
                    p = (state.get("path_human", ""), state.get("backend", ""))
                    pending_per_path[p] = pending_per_path.get(p, 0) + 1
            if cursor == 0:
                break

    # Update pending gauge
    if CANARY_PENDING is not None:
        for (path, backend), n in pending_per_path.items():
            try:
                CANARY_PENDING.labels(path=path, backend=backend).set(n)
            except Exception:
                pass

    _LAST_CYCLE_STATS["judged"] = judged
    _LAST_CYCLE_STATS["pending"] = pending
    if judged or pending:
        logger.info(f"[CanaryJudge] cycle done: judged={judged} pending={pending}")


# Track most recent cycle counts for snapshot() — populated by _cycle_once.
_LAST_CYCLE_STATS: Dict[str, Any] = {"judged": 0, "pending": 0}


class CanaryJudge(BackgroundWorker):
    """Leader-elected canary outcome judge (§pass27 Phase 1: BackgroundWorker)."""

    worker_id = "canary_judge"
    leader_key = CANARY_JUDGE_LEADER_KEY
    interval_sec = CANARY_JUDGE_INTERVAL_SEC
    # Don't delay the judge — runner fires every 5s; aggressive cold-start
    # would let the first batch of fires age past the SLO window.
    cold_start_delay_sec = 1

    def _should_run(self) -> bool:
        return CANARY_ENABLED and CANARY_JUDGE_ENABLED

    async def _cycle_once(self) -> None:
        # Snapshot stats are populated by _judge_cycle via module global.
        _LAST_CYCLE_STATS["judged"] = 0
        _LAST_CYCLE_STATS["pending"] = 0
        await _judge_cycle()
        self._stats = dict(_LAST_CYCLE_STATS)


_judge: Optional[CanaryJudge] = None


async def start_canary_judge() -> None:
    global _judge
    if _judge is None:
        _judge = CanaryJudge()
    await _judge.start()


async def stop_canary_judge() -> None:
    global _judge
    if _judge is not None:
        await _judge.stop()


def get_canary_judge() -> Optional[CanaryJudge]:
    """Accessor for admin endpoints (returns None pre-start)."""
    return _judge
