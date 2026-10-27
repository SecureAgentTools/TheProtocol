"""Prometheus metrics for the TEGStreamProxy / Flusher / Subscriber.

Defined in a separate module so the metric registration is global and
idempotent across worker imports.  The names are namespaced with
``tx_stream_*`` to make Grafana queries unambiguous.
"""
from __future__ import annotations

import os

try:
    from prometheus_client import Counter, Gauge, Histogram

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False
    Counter = Gauge = Histogram = None  # type: ignore[assignment]


def _registry_label() -> str:
    return os.getenv("REGISTRY_NAME", "registry")


# ----------------------------------------------------------------------
# Metric definitions — created once at import time.
# ----------------------------------------------------------------------
if _PROM_AVAILABLE:
    TX_STREAM_SUBMIT_TOTAL = Counter(
        "tx_stream_submit_total",
        "Submit-funnel outcomes for the TEG stream proxy",
        labelnames=["registry", "outcome"],
    )
    TX_STREAM_FLUSH_TOTAL = Counter(
        "tx_stream_flush_total",
        "Flush outcomes for the TEG stream proxy flusher",
        labelnames=["registry", "outcome"],
    )
    TX_STREAM_FLUSH_SIZE = Histogram(
        "tx_stream_flush_size",
        "Distribution of batch sizes per flush",
        labelnames=["registry"],
        buckets=(1, 2, 5, 10, 25, 50, 100, 200, 500),
    )
    TX_STREAM_FLUSH_DURATION_SECONDS = Histogram(
        "tx_stream_flush_duration_seconds",
        "Wall-clock duration of one flush (XREADGROUP + POST + PUBLISH + XACK)",
        labelnames=["registry"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    )
    TX_STREAM_REQUEST_DURATION_SECONDS = Histogram(
        "tx_stream_request_duration_seconds",
        "End-to-end (submit → resolve) latency observed by the caller",
        labelnames=["registry"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    TX_STREAM_PENDING_SIZE = Gauge(
        "tx_stream_pending_size",
        "Number of in-flight Futures awaiting a result on this worker",
        labelnames=["registry"],
    )
    TX_STREAM_XLEN = Gauge(
        "tx_stream_xlen",
        "Length of the Redis stream (sampled by the leader flusher)",
        labelnames=["registry"],
    )
    TX_STREAM_PUBSUB_RESOLVED_TOTAL = Counter(
        "tx_stream_pubsub_resolved_total",
        "Pub/Sub message → Future resolution outcomes",
        labelnames=["registry", "outcome"],
    )


def inc_submit(outcome: str) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_SUBMIT_TOTAL.labels(registry=_registry_label(), outcome=outcome).inc()
    except Exception:
        pass


def inc_flush(outcome: str) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_FLUSH_TOTAL.labels(registry=_registry_label(), outcome=outcome).inc()
    except Exception:
        pass


def observe_flush_size(n: int) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_FLUSH_SIZE.labels(registry=_registry_label()).observe(n)
    except Exception:
        pass


def observe_flush_duration(seconds: float) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_FLUSH_DURATION_SECONDS.labels(registry=_registry_label()).observe(seconds)
    except Exception:
        pass


def observe_request_duration(seconds: float) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_REQUEST_DURATION_SECONDS.labels(registry=_registry_label()).observe(seconds)
    except Exception:
        pass


def set_pending_size(n: int) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_PENDING_SIZE.labels(registry=_registry_label()).set(n)
    except Exception:
        pass


def set_xlen(n: int) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_XLEN.labels(registry=_registry_label()).set(n)
    except Exception:
        pass


def inc_pubsub_resolved(outcome: str) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        TX_STREAM_PUBSUB_RESOLVED_TOTAL.labels(
            registry=_registry_label(), outcome=outcome
        ).inc()
    except Exception:
        pass
