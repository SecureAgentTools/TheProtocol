"""
Reactor: canary validator
============================

Per-frame leader-elected reactors that subscribe to the 5 events a canary
fire produces, filter by correlation/transfer_id matching the canary
runner's Redis index, and update the in-flight test's Redis hash so the
canary_judge (Phase 5) can decide pass/fail.

Five reactor classes (one per event type — reactor framework requires
unique leader_key per event_type subscription):
  CanaryTokensTransferredReactor       — intra-frame credit + cross-frame leg
  CanaryTransactionFeeCollectedReactor — fee event on every transfer
  CanaryCrossFrameInitiatedReactor     — sender-side lock for cross-frame
  CanaryCrossFrameSettledReactor       — receiver-side credit + bridge back
  CanaryCrossFrameRefundedReactor      — saga-refund (failure case)

All five share `_record_canary_event()`. They run on EVERY registry
that has the reactor framework enabled (via the existing leader-elect
gate). The validator is a no-op when no Redis index entry matches —
i.e., when the event isn't from a canary fire — so it's safe to run
cluster-wide.

Lookup flow:
  1. Extract transfer_id (or transaction_id) from event_data.
  2. Try `canary_xfer:<transfer_id>` → test_id (set by runner).
  3. If hit, read `canary:<test_id>` hash + write the per-event timestamp
     field (e.g., `tokens_xfer_seen_iso`).
  4. If miss, this isn't a canary event; silently skip.

The Redis write also bumps a Prometheus counter so we can see
"validator saw N events for canaries" in Grafana.
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)

CANARY_VALIDATOR_ENABLED = os.environ.get("CANARY_VALIDATOR_ENABLED", "true").lower() == "true"


# -- Prometheus instrumentation (best-effort) --------------------------------
try:
    from prometheus_client import Counter as _CCounter

    CANARY_VALIDATOR_SEEN = _CCounter(
        "canary_validator_seen_event",
        "Canary validator observations of expected events",
        labelnames=["event_type", "frame"],
    )
except Exception:  # pragma: no cover
    CANARY_VALIDATOR_SEEN = None


def _frame_label() -> str:
    """Return short frame label for Prom metric labels."""
    td = os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")
    if td.startswith("frame-b"):
        return "frame-b"
    return "frame-a"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _record_canary_event(
    *,
    event_type: str,
    transfer_id: Optional[str],
    field: str,
    extra: Optional[dict] = None,
    memo: Optional[str] = None,
) -> None:
    """Look up the canary test by transfer_id (or memo as fallback) and stamp
    the per-event field.

    2026-05-04: Added memo fallback to close the WS race where the validator
    catches CrossFrameTransferInitiated on the local WS (~50ms after emit)
    BEFORE canary_runner writes `canary_xfer:<transfer_id>` (~150ms after HTTP
    response). canary_runner now pre-sets `canary:<test_id>` and
    `canary_corr:<test_id>` BEFORE the HTTP call, so this fallback resolves.

    Silently skips when:
      - validator disabled
      - Redis unavailable
      - both transfer_id AND memo missing from event
      - no matching reverse-index for either (i.e., not a canary event)
    """
    if not CANARY_VALIDATOR_ENABLED:
        return
    if not transfer_id and not memo:
        return
    from .leader import get_redis
    redis = await get_redis()
    if redis is None:
        return
    try:
        test_id = None
        # Primary lookup: transfer_id reverse-index (set by canary_runner AFTER HTTP)
        if transfer_id:
            test_id_bytes = await redis.get(f"canary_xfer:{transfer_id}")
            if test_id_bytes:
                test_id = (
                    test_id_bytes.decode()
                    if isinstance(test_id_bytes, (bytes, bytearray))
                    else test_id_bytes
                )
        # Fallback: memo equals test_id (canary_runner sets memo=test_id on every fire).
        # Verify the canary state hash exists to avoid writing for non-canary events
        # whose memo happens to start with "canary-".
        # 2026-05-04 / Phase 7: 2pc cross-registry path emits TokensTransferred /
        # TransactionFeeCollected with memo wrapped as `cross_registry:<original>`,
        # so strip a known prefix before the canary- check.
        if not test_id and memo:
            stripped = memo
            # 2026-05-16: strip known event-type prefixes so memo carries through.
            # `cross_frame_async:` prefix is added by TEG when the cross-frame async
            # path emits TokensTransferred. `cross_registry:` is the legacy 2pc
            # wrapper. Both wrap the original test_id memo without losing it.
            for _prefix in ("cross_registry:", "cross_frame_async:"):
                if stripped.startswith(_prefix):
                    stripped = stripped[len(_prefix):]
                    break
            if stripped.startswith("canary-") and await redis.exists(f"canary:{stripped}"):
                test_id = stripped
        if not test_id:
            return
        key = f"canary:{test_id}"
        update = {field: _now_iso()}
        if extra:
            update.update(extra)
        await redis.hset(key, mapping=update)
        # Re-extend TTL so judge has time to sweep before expiry
        await redis.expire(key, 600)
        if CANARY_VALIDATOR_SEEN is not None:
            try:
                CANARY_VALIDATOR_SEEN.labels(event_type=event_type, frame=_frame_label()).inc()
            except Exception:
                pass
        logger.info(
            f"[CanaryValidator] {event_type} seen for {test_id} (transfer_id={transfer_id})"
        )
    except Exception as e:
        logger.debug(f"[CanaryValidator] Redis update failed: {e}")


# ---------------------------------------------------------------------------
# Reactor subclasses (one per event type)
# ---------------------------------------------------------------------------


def _extract_memo(event_data: dict) -> Optional[str]:
    """Extract canary correlation marker from event payload.
    Different event types carry it under different keys: memo (TEG events) vs
    message (registry-emitted CrossFrame*) vs correlation_id (rare)."""
    return (
        event_data.get("memo")
        or event_data.get("message")
        or event_data.get("correlation_id")
    )


class CanaryTokensTransferredReactor(EventStoreReactor):
    event_type = "TokensTransferred"
    leader_key = "reactor_canary_tokens_transferred"
    name = "CanaryValidator-TokensTransferred"

    async def handle_event(self, event_data: dict) -> None:
        tid = event_data.get("transaction_id") or event_data.get("transfer_id")
        await _record_canary_event(
            event_type="TokensTransferred",
            transfer_id=tid,
            field="tokens_xfer_seen_iso",
            memo=_extract_memo(event_data),
        )


class CanaryTransactionFeeCollectedReactor(EventStoreReactor):
    event_type = "TransactionFeeCollected"
    leader_key = "reactor_canary_fee_collected"
    name = "CanaryValidator-TransactionFeeCollected"

    async def handle_event(self, event_data: dict) -> None:
        tid = event_data.get("transaction_id") or event_data.get("transfer_id")
        await _record_canary_event(
            event_type="TransactionFeeCollected",
            transfer_id=tid,
            field="fee_collected_seen_iso",
            memo=_extract_memo(event_data),
        )


class CanaryCrossFrameInitiatedReactor(EventStoreReactor):
    event_type = "CrossFrameTransferInitiated"
    leader_key = "reactor_canary_cf_initiated"
    name = "CanaryValidator-CrossFrameInitiated"

    async def handle_event(self, event_data: dict) -> None:
        tid = event_data.get("transfer_id") or event_data.get("transaction_id")
        await _record_canary_event(
            event_type="CrossFrameTransferInitiated",
            transfer_id=tid,
            field="cf_initiated_seen_iso",
            memo=_extract_memo(event_data),
        )


class CanaryCrossFrameSettledReactor(EventStoreReactor):
    event_type = "CrossFrameTransferSettled"
    leader_key = "reactor_canary_cf_settled"
    name = "CanaryValidator-CrossFrameSettled"

    async def handle_event(self, event_data: dict) -> None:
        tid = event_data.get("transfer_id") or event_data.get("transaction_id")
        # Distinguish local vs remote: source_frame matches THIS frame → local Settled
        # source_frame DIFFERS from THIS frame → SF-4 replicated Settled (remote-frame original)
        source_frame = event_data.get("source_frame", "")
        local_frame = os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")
        field = (
            "cf_settled_local_seen_iso"
            if source_frame == local_frame
            else "cf_settled_remote_seen_iso"
        )
        await _record_canary_event(
            event_type="CrossFrameTransferSettled",
            transfer_id=tid,
            field=field,
            memo=_extract_memo(event_data),
        )


class CanaryCrossFrameRefundedReactor(EventStoreReactor):
    event_type = "CrossFrameTransferRefunded"
    leader_key = "reactor_canary_cf_refunded"
    name = "CanaryValidator-CrossFrameRefunded"

    async def handle_event(self, event_data: dict) -> None:
        tid = event_data.get("transfer_id") or event_data.get("transaction_id")
        await _record_canary_event(
            event_type="CrossFrameTransferRefunded",
            transfer_id=tid,
            field="cf_refunded_seen_iso",
            extra={"failure_signal": "refunded"},
            memo=_extract_memo(event_data),
        )


# ---------------------------------------------------------------------------
# Module API — start_all / stop_all all 5 validator reactors together
# ---------------------------------------------------------------------------

_instances: list = []


async def start_all() -> None:
    """Start all 5 canary validator reactors. No-op if CANARY_VALIDATOR_ENABLED!=true."""
    global _instances
    if not CANARY_VALIDATOR_ENABLED:
        logger.info(
            "[CanaryValidator] disabled (CANARY_VALIDATOR_ENABLED!=true); skipping start"
        )
        return
    if _instances:
        return
    _instances = [
        CanaryTokensTransferredReactor(),
        CanaryTransactionFeeCollectedReactor(),
        CanaryCrossFrameInitiatedReactor(),
        CanaryCrossFrameSettledReactor(),
        CanaryCrossFrameRefundedReactor(),
    ]
    for r in _instances:
        await r.start()
    logger.info(f"[CanaryValidator] started {len(_instances)} reactor(s)")


async def stop_all() -> None:
    global _instances
    for r in _instances:
        try:
            await r.stop()
        except Exception:
            pass
    _instances = []
