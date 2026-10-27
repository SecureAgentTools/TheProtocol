"""WARNING-level observability — the blind spot that let §DNSFIX run five hours unseen.

Every dashboard and alert in this stack watches one of three things: the supply invariant (Δ),
a health endpoint, or a stuck-state SLO. On 2026-07-26 a DNS resolver saturation degraded the
whole box for five hours and **not one of them moved**, correctly:

  * Δ stayed 0/0/0 — no money was ever at risk;
  * every /health returned 200 — the services were up;
  * `AgoraSettlementStuck` stayed inactive — settlements were FAILING and then SUCCEEDING on
    retry, so nothing was ever stuck;
  * `HighErrorRate` watches 5xx > 5% — real 5xx peaked at 0.20%, because the failures surfaced
    as client disconnects (nginx 499), not server errors.

The actual signal — 80-100 `Temporary failure in name resolution` per minute — was logged at
**WARNING**, and nothing in the system turns log volume into a number. A degradation where
everything still works, just worse and with retries, was structurally invisible.

This module closes that. One logging.Handler on the root logger increments a counter per record
at WARNING and above, bucketed into a **small fixed set of categories**. Deliberately no logger
name and no message label: unbounded label values are how a metrics backend gets destroyed, and
the question this answers ("is a warning class spiking?") does not need them. Follow up in the
logs once the counter tells you where to look.

Cost: one dict lookup and a few regex-free substring checks per warning. Nothing is logged, so
there is no recursion risk, and every failure path is swallowed — instrumentation must never be
able to break the thing it measures.
"""
from __future__ import annotations

import logging

try:  # prometheus_client is present in prod; absent in some test contexts
    from prometheus_client import Counter as _Counter

    LOG_RECORDS_TOTAL = _Counter(
        "registry_log_records_total",
        "Log records emitted at WARNING or above, bucketed by coarse category",
        labelnames=["level", "category"],
    )
    _AVAILABLE = True
except Exception:  # pragma: no cover
    LOG_RECORDS_TOTAL = None  # type: ignore[assignment]
    _AVAILABLE = False


# Ordered: first match wins, so put the specific before the general.
# Keep this list SHORT — every entry is a label value and therefore a time series.
_CATEGORIES = (
    ("dns_resolution", ("temporary failure in name resolution", "name or service not known",
                        "nodename nor servname", "[errno -3]", "[errno -2]")),
    ("redis",          ("redis", "connection pool", "pubsub")),
    ("teg",            ("teg api", "teg token", "teg stream")),
    ("peer",           ("cannot resolve peer", "unresolvable caller", "peer registry")),
    ("timeout",        ("timeout", "timed out", "readtimeout", "connecttimeout")),
    ("settlement",     ("settle", "settlement", "escrow")),
    ("mtls",           ("svid", "spiffe", "certificate verify", "mtls")),
    # Added 2026-07-26 after the FIRST live read: "other" was 158/min, which tells an operator
    # nothing. These are the benign-but-loud classes that were drowning the real signal.
    ("disconnect",     ("no response returned",)),          # client hung up; pairs with nginx 499
    ("http_expected",  ("http exception on", "404 - not found", "signature has expired")),
    ("ratelimit",      ("[ratelimiter]", "rate limit")),
)


def _http_refusal(low: str) -> bool:
    """§MCPTEST30 (V0640): the errors module's line for a 4xx answer, `http exception on <method> <path>: 4xx - ...`.
    A path holds no space, so the first ": " after the method is the status's: a 5xx whose detail quotes a 404 is not
    one."""
    if not low.startswith("http exception on "):
        return False
    i = low.find(": ", len("http exception on "))
    return i != -1 and low[i + 2:i + 3] == "4" and low[i + 3:i + 5].isdigit()


def _categorise(msg: str) -> str:
    low = msg.lower()
    # §MCPTEST30 (V0640): a refused request is the route's word whatever its path says. "HTTP exception on GET
    # /agents/fedsuite-repbond-settlepayer-8162f104: 404 - Not Found" was counted as settlement ("settle" comes before
    # http_expected) and fired SettlementFailureRate with the sandbox's federation suite agents (2026-10-24); a 5xx
    # still falls to the keyword classes below.
    if _http_refusal(low):
        return "http_expected"
    for name, needles in _CATEGORIES:
        for n in needles:
            if n in low:
                return name
    return "other"


class _MetricsHandler(logging.Handler):
    """Counts records; never formats unless it has to, never raises."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            if record.levelno < logging.WARNING or LOG_RECORDS_TOTAL is None:
                return
            # getMessage() applies args without touching handlers, so no recursion.
            LOG_RECORDS_TOTAL.labels(
                level=record.levelname,
                category=_categorise(record.getMessage()),
            ).inc()
        except Exception:
            pass  # instrumentation must never break the caller

    def handleError(self, record):  # noqa: D102
        pass


_installed = False


def install() -> bool:
    """Attach to the root logger. Idempotent; safe to call from startup more than once."""
    global _installed
    if _installed or not _AVAILABLE:
        return False
    h = _MetricsHandler(level=logging.WARNING)
    h.setFormatter(None)
    logging.getLogger().addHandler(h)
    _installed = True
    logging.getLogger(__name__).info(
        "[LogMetrics] registry_log_records_total{level,category} installed — "
        "WARNING-level volume is now alertable"
    )
    return True
