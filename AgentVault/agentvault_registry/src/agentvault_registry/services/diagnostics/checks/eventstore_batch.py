"""EventStore batch-failure check (mainframe only).

Scans the EventStore container's recent log lines for "Batch failed" markers
that indicate the Kafka consumer is rejecting batches (usually projection
errors). Any non-zero count → fail.
"""

import re
import time

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "eventstore-batch-failures"
TITLE = "EventStore batch failures"
DESCRIPTION = "Scans EventStore logs for batch failures during projection replay."
CATEGORY = "logs"
COST_MS = 600

_BATCH_FAIL_RE = re.compile(r"Batch failed", re.IGNORECASE)


def applies(target: dict) -> bool:
    return target.get("role") == "mainframe"


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    es_container = target["containers"].get("event_store")
    if not es_container:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="no event_store container configured",
        )
    log_excerpt = await probe.logs(
        es_container,
        tail=4000,
        grep_pattern=r"Batch failed|projection.*error|IntegrityError",
        max_bytes=8192,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    fail_count = len(_BATCH_FAIL_RE.findall(log_excerpt))
    details = {"batch_failures_recent": fail_count}
    if fail_count > 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"{fail_count} batch failure(s) in recent logs",
            details=details,
            evidence=log_excerpt[-2048:],
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="EventStore projection is rejecting batches — investigate before remediation.",
                destructive=False,
            ),
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary="no batch failures in recent logs",
        details=details,
    )
