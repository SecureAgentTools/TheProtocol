"""Kafka consumer lag check (mainframe only).

Uses redpanda's `rpk` CLI inside the frame's redpanda container to describe the
EventStore's consumer group. Lag > 100 OR group state ≠ Stable → warn/fail.

§SOVKIT K1 (2026-09-14): the broker is named from the TARGET, never from a hand list. A runner-built frame's broker
is `<frame>-redpanda` (its event store is `<frame>-event-store`, its registry `<frame>-registry`; the containers map
carries both) and Frame A's is `agentvault_redpanda`; the four legacy names stay as the last resort. On a K1 frame the
broker requires SASL/SCRAM over TLS: the container's own RPK_* environment (the template) makes `rpk` inside it
authenticate as the store's user, so the command below needs no flags; on an older broker without SASL the same
command works as before.
"""

import re
import time

from ..schemas import CheckResult

CHECK_ID = "kafka-consumer-lag"
TITLE = "Kafka consumer lag"
DESCRIPTION = "EventStore Kafka consumer group must have <100 lag and Stable state."
CATEGORY = "kafka"
COST_MS = 1500

# The last resort, after the names derived from the target (see `_candidate_containers`): the redpanda container's
# name varied between the legacy deployments.
KAFKA_CONTAINER_CANDIDATES = (
    "agentvault_redpanda",
    "redpanda",
    "agentvault_kafka",
    "kafka",
)
CONSUMER_GROUP_CANDIDATES = (
    "eventstore-consumer",
    "event-store-consumer",
    "agentvault-event-store",
)

# rpk uses a 2-column "key   value" header block:
#   GROUP        eventstore-consumer
#   STATE        Stable
#   TOTAL-LAG    3
_TOTAL_LAG_RE = re.compile(r"^\s*TOTAL-LAG\s+(\d+)", re.IGNORECASE | re.MULTILINE)
_STATE_RE = re.compile(r"^\s*STATE\s+(\S+)", re.IGNORECASE | re.MULTILINE)
# Per-partition LAG column (used as fallback when TOTAL-LAG is absent)
_LAG_COL_RE = re.compile(r"^\S+\s+\d+\s+\d+\s+\d+\s+(\d+)\s+", re.MULTILINE)

_DERIVE = (
    # (containers-map key, the suffix that key's name carries, the broker's suffix)
    ("redpanda", "", ""),
    ("kafka", "", ""),
    ("event_store", "-event-store", "-redpanda"),
    ("event_store", "_event_store", "_redpanda"),
    ("registry", "-registry", "-redpanda"),
    ("registry", "_registry_a", "_redpanda"),
)


def _candidate_containers(target: dict) -> list[str]:
    """The broker names this target implies, most specific first, then the legacy list; no duplicates."""
    out: list[str] = []
    containers = target.get("containers") or {}
    for key, suffix, broker_suffix in _DERIVE:
        name = containers.get(key)
        if not name:
            continue
        if not suffix:
            cand = name
        elif name.endswith(suffix):
            cand = name[: -len(suffix)] + broker_suffix
        else:
            continue
        if cand not in out:
            out.append(cand)
    for name in KAFKA_CONTAINER_CANDIDATES:
        if name not in out:
            out.append(name)
    return out


def applies(target: dict) -> bool:
    return target.get("role") == "mainframe"


async def _find_kafka_container(probe, target: dict) -> str | None:
    for name in _candidate_containers(target):
        if await probe.container_exists(name):
            return name
    return None


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    container = await _find_kafka_container(probe, target)
    if not container:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="no redpanda/kafka container found — Kafka may be disabled",
            details={"tried": _candidate_containers(target)},
        )

    last_output = ""
    last_exit = -1
    found_group = None
    for group in CONSUMER_GROUP_CANDIDATES:
        exit_code, output = await probe.exec_in(
            container,
            ["rpk", "group", "describe", group],
            timeout=5,
        )
        last_output, last_exit = output, exit_code
        if exit_code == 0 and "GROUP" in output.upper():
            found_group = group
            break

    latency_ms = int((time.monotonic() - started) * 1000)

    if not found_group:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=latency_ms,
            summary=f"consumer group not found (tried {len(CONSUMER_GROUP_CANDIDATES)})",
            details={"container": container, "exit": last_exit},
            evidence=last_output[:1024],
        )

    total_lag_match = _TOTAL_LAG_RE.search(last_output)
    if total_lag_match:
        total_lag = int(total_lag_match.group(1))
    else:
        partition_lags = [int(n) for n in _LAG_COL_RE.findall(last_output)]
        total_lag = sum(partition_lags) if partition_lags else 0
    state_match = _STATE_RE.search(last_output)
    state = state_match.group(1) if state_match else "Unknown"

    details = {
        "group": found_group,
        "container": container,
        "total_lag": total_lag,
        "state": state,
    }

    if state.lower() != "stable":
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"group state={state}",
            details=details,
            evidence=last_output[:2048],
        )
    if total_lag > 100:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="warn",
            latency_ms=latency_ms,
            summary=f"lag={total_lag}",
            details=details,
            evidence=last_output[:2048],
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"lag={total_lag}, state={state}",
        details=details,
    )
