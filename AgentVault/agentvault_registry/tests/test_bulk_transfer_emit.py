"""§S4 — a completed bulk transfer whose ledger events fail must not vanish.

WHY THIS TEST EXISTS. `TEG_BULK_PROXY=true` on every node, so coalesced
transfers flush through `TEGBulkProxy._flush`, and the /teg/transfer handler
deliberately skips its own `_emit_transfer_events()` on that path. That makes
`_emit_bulk_transfer_events` the ONLY site where a bulk transfer becomes
`TokensTransferred` / `TransactionFeeCollected` — the supply invariant's input.

It used to read `except Exception: pass  # Non-fatal — transfer succeeded`.
Both halves of that comment are true, and together they are exactly how the
money could move while the EventStore never heard, with nothing anywhere
saying so. Non-fatal is kept. Invisible is not.
"""
from __future__ import annotations

import ast
import logging
import pathlib

import pytest

from agentvault_registry.routers import teg_integration as tg


class _Emitter:
    """Records emit_background calls; optionally explodes on the first one."""

    def __init__(self, explode: bool = False):
        self.calls: list[dict] = []
        self.explode = explode

    def emit_background(self, **kw):
        if self.explode:
            raise RuntimeError("EventStore unreachable")
        self.calls.append(kw)


class _Counter:
    def __init__(self):
        self.labels_seen: list[dict] = []
        self.incs = 0

    def labels(self, **kw):
        self.labels_seen.append(kw)
        return self

    def inc(self):
        self.incs += 1


ITEM = {
    "sender_did": "did:theprotocol:sender",
    "receiver_did": "did:theprotocol:receiver",
    "amount": "1.5",
    "fee_amount": "0.0075",
    "message": "hi",
}
RESULT = {"status": "completed", "transaction_id": "tx-abc-123"}


@pytest.fixture
def counter(monkeypatch):
    c = _Counter()
    monkeypatch.setattr(tg, "TRANSFER_EVENT_EMIT_FAILURES", c)
    return c


def _install(monkeypatch, emitter):
    monkeypatch.setattr(
        "agentvault_registry.event_emitter.get_event_emitter", lambda: emitter
    )


def test_happy_path_emits_both_events_with_dedup_keys(monkeypatch, counter):
    em = _Emitter()
    _install(monkeypatch, em)

    tg._emit_bulk_transfer_events(ITEM, RESULT)

    kinds = [c["event_type"] for c in em.calls]
    assert kinds == ["TokensTransferred", "TransactionFeeCollected"], kinds
    # The EventStore dedups on these exact keys (PART 3, exactly-once).
    assert em.calls[0]["idempotency_key"] == "xfer-tx-abc-123"
    assert em.calls[1]["idempotency_key"] == "fee-tx-abc-123"
    assert em.calls[0]["data"]["amount"] == "1.5"
    # CONTROL: a healthy emit must NOT move the failure counter, or the counter
    # would be measuring traffic instead of failures.
    assert counter.incs == 0


def test_zero_fee_emits_only_the_transfer(monkeypatch, counter):
    em = _Emitter()
    _install(monkeypatch, em)

    tg._emit_bulk_transfer_events({**ITEM, "fee_amount": "0"}, RESULT)

    assert [c["event_type"] for c in em.calls] == ["TokensTransferred"]
    assert counter.incs == 0


def test_emit_failure_is_counted_and_logged_never_raised(monkeypatch, counter, caplog):
    """The defect this whole exercise was about: money moved, ledger silent."""
    _install(monkeypatch, _Emitter(explode=True))

    with caplog.at_level(logging.ERROR, logger=tg.logger.name):
        tg._emit_bulk_transfer_events(ITEM, RESULT)  # must NOT raise

    assert counter.incs == 1, "a failed ledger emit must be counted"
    assert counter.labels_seen == [{"path": "bulk"}]

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a failed ledger emit must be logged at ERROR"
    msg = errors[0].getMessage()
    # The operator needs the transaction id to reconcile; a bare 'emit failed'
    # names nothing and cannot be acted on.
    assert "tx-abc-123" in msg, msg
    assert "did:theprotocol:sender" in msg, msg


def test_malformed_item_is_counted_not_raised(monkeypatch, counter):
    """A KeyError inside the emit block is the same class as a dead EventStore."""
    _install(monkeypatch, _Emitter())

    tg._emit_bulk_transfer_events({}, RESULT)  # no sender_did

    assert counter.incs == 1


def test_missing_counter_does_not_break_the_money_path(monkeypatch, caplog):
    """prometheus_client absent must degrade to logging, never to an exception."""
    monkeypatch.setattr(tg, "TRANSFER_EVENT_EMIT_FAILURES", None)
    _install(monkeypatch, _Emitter(explode=True))

    with caplog.at_level(logging.ERROR, logger=tg.logger.name):
        tg._emit_bulk_transfer_events(ITEM, RESULT)

    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_the_bulk_flush_still_calls_it():
    """Guard the WIRING, not just the function.

    The extraction is only worth anything if `_flush` still calls it; a silent
    unwiring would leave every test above green while the live path emitted
    nothing at all.
    """
    src = pathlib.Path(tg.__file__).read_text()
    tree = ast.parse(src)
    flush = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_flush"
    )
    called = {
        n.func.id for n in ast.walk(flush)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_emit_bulk_transfer_events" in called, (
        "TEGBulkProxy._flush no longer emits ledger events — coalesced transfers "
        "would move money with nothing reaching the EventStore"
    )
