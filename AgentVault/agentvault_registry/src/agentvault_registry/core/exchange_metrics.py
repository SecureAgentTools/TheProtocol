"""
AGORA Prometheus instrumentation (§V0064, 2026-06-12).

Six metrics behind the staged vmalert rules
(PRODUCTION_DOCS/07_MONITORING/agora_vmalert_rules.staged.yml):

  agora_orders_total{side,type}    counter  — orders accepted by place_order
  agora_trades_total               counter  — CLOB fills
  agora_notional_total             counter  — matched notional (venue currency units)
  agora_settlement_lag_seconds     gauge    — age of the OLDEST pending_settlement trade
  agora_escrow_balance             gauge    — teg:system:exchange_escrow actual balance
  agora_invariant_delta            gauge    — I-X3 actual−expected (0 = conserved)

Same multi-worker semantics as the a2a_payment counters: counters are
per-uvicorn-worker (scrape lands on one worker); the gauges are written by
the leader-elected settlement worker, so they live in the leader's process.
Accepted platform-wide caveat — alert rules use increase()/presence, not
cross-worker exactness. Import is guarded: prometheus_client missing → every
helper is a silent no-op (3rd-party/standalone images stay unaffected).
"""
import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge

    AGORA_ORDERS_TOTAL = _Counter(
        "agora_orders_total",
        "AGORA orders accepted (post-validation, pre-match)",
        labelnames=["side", "type"],
    )
    AGORA_TRADES_TOTAL = _Counter(
        "agora_trades_total",
        "AGORA CLOB fills executed",
    )
    AGORA_NOTIONAL_TOTAL = _Counter(
        "agora_notional_total",
        "AGORA matched notional, market currency units",
    )
    AGORA_SETTLEMENT_LAG_SECONDS = _Gauge(
        "agora_settlement_lag_seconds",
        "Age in seconds of the oldest trade still pending settlement (0 = drained)",
    )
    AGORA_ESCROW_BALANCE = _Gauge(
        "agora_escrow_balance",
        "Actual TEG balance of teg:system:exchange_escrow",
    )
    AGORA_INVARIANT_DELTA = _Gauge(
        "agora_invariant_delta",
        "I-X3 escrow delta (actual minus expected); nonzero sustained = conservation breach",
    )
    AGORA_FUNDING_IN_TRANSITION = _Gauge(
        "agora_funding_orders_in_transition",
        "Orders in 'funding' status — the ONE legitimate transient I-X3 window",
    )
    AGORA_SETTLEMENT_STUCK = _Gauge(
        "agora_settlement_stuck_over_slo",
        "I-X4: trades pending_settlement older than EXCHANGE_SETTLE_SLO_SEC",
    )
    # §REPATLANE (V0603): what the passport gateway's payouts came back as (services/payout_outcome.py). `hold` is a
    # payout that may have moved and is never sent again on its own: its rise is what an operator reads the ledger for.
    AGORA_REPAT_OUTCOMES = _Counter(
        "agora_repat_outcomes_total",
        "AGORA gateway payout outcomes by pass (credit, bundle, store, legacy) and kind (paid, retry, wait, "
        "sender_refused, hold)",
        labelnames=["pass_", "kind"],
    )
    _PROM = True
except ImportError:  # pragma: no cover — slim images without prometheus_client
    _PROM = False
    AGORA_ORDERS_TOTAL = None  # type: ignore[assignment]
    AGORA_TRADES_TOTAL = None  # type: ignore[assignment]
    AGORA_NOTIONAL_TOTAL = None  # type: ignore[assignment]
    AGORA_SETTLEMENT_LAG_SECONDS = None  # type: ignore[assignment]
    AGORA_ESCROW_BALANCE = None  # type: ignore[assignment]
    AGORA_INVARIANT_DELTA = None  # type: ignore[assignment]
    AGORA_FUNDING_IN_TRANSITION = None  # type: ignore[assignment]
    AGORA_SETTLEMENT_STUCK = None  # type: ignore[assignment]
    AGORA_REPAT_OUTCOMES = None  # type: ignore[assignment]


def agora_repat_outcome(pass_: str, kind: str, n: int = 1) -> None:
    if _PROM and n:
        try:
            AGORA_REPAT_OUTCOMES.labels(pass_=pass_, kind=kind).inc(n)
        except Exception:  # never let telemetry touch the money path
            pass


def agora_order_placed(side: str, order_type: str) -> None:
    if _PROM:
        try:
            AGORA_ORDERS_TOTAL.labels(side=side, type=order_type).inc()
        except Exception:  # never let telemetry touch the money path
            pass


def agora_trade_executed(notional: float) -> None:
    if _PROM:
        try:
            AGORA_TRADES_TOTAL.inc()
            if notional > 0:
                AGORA_NOTIONAL_TOTAL.inc(notional)
        except Exception:
            pass


def agora_set_settlement_lag(seconds: float) -> None:
    if _PROM:
        try:
            AGORA_SETTLEMENT_LAG_SECONDS.set(max(0.0, seconds))
        except Exception:
            pass


def agora_set_invariants(escrow=None, delta=None, funding_n=None, stuck=None) -> None:
    """Set whichever invariant gauges are known (None = leave untouched —
    e.g. a TEG read failure must not zero a real escrow reading)."""
    if _PROM:
        try:
            if escrow is not None:
                AGORA_ESCROW_BALANCE.set(float(escrow))
            if delta is not None:
                AGORA_INVARIANT_DELTA.set(float(delta))
            if funding_n is not None:
                AGORA_FUNDING_IN_TRANSITION.set(int(funding_n))
            if stuck is not None:
                AGORA_SETTLEMENT_STUCK.set(int(stuck))
        except Exception:
            pass
