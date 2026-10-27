"""§SILENT (2026-09-14) — a ledger emit that fails after the fact it describes has happened is never silent.

`emit_or_report` (event_emitter.py) replaces the `except Exception: pass` around the value emits in the token bridge
and A2A authorize: a failure is logged at ERROR with the event's type, aggregate and key, counted in
`registry_value_emit_failed_total`, and returned as False; it is never raised (the money already moved) and never
silent. The background wrapper reports the same way. The last tests run the emission census over the tree: the six
value sites the nightly named no longer swallow, and the two ratchets read at or under their baselines.
"""
from __future__ import annotations

import logging

import pytest

from agentvault_registry import event_emitter as ee
from agentvault_registry.api_tests.federation_suite.tests import test_event_emission_contract as census


class _Emitter:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def emit(self, **kw):
        self.calls.append(kw)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _count(event_type: str) -> float:
    c = ee._value_emit_failed_total
    if c is None:
        return -1.0
    return c.labels(event_type=event_type)._value.get()


async def test_a_successful_emit_returns_true_and_reports_nothing(caplog):
    em = _Emitter(True)
    with caplog.at_level(logging.ERROR, logger=ee.logger.name):
        ok = await ee.emit_or_report(em, event_type="TokensBridgeLocked", aggregate_id="btx-1", data={"a": 1}, idempotency_key="k1", where="t")
    assert ok is True and em.calls[0]["idempotency_key"] == "k1" and em.calls[0]["event_type"] == "TokensBridgeLocked"
    assert not [r for r in caplog.records if "EMIT-LOST" in r.getMessage()]


async def test_a_raising_emit_is_logged_counted_and_returned_false_never_raised(caplog):
    before = _count("TokensBridgeUnlocked")
    em = _Emitter(ConnectionError("event store down"))
    with caplog.at_level(logging.ERROR, logger=ee.logger.name):
        ok = await ee.emit_or_report(em, event_type="TokensBridgeUnlocked", aggregate_id="btx-2", data={}, idempotency_key="k2", where="bridge.unlock")
    assert ok is False
    lost = [r.getMessage() for r in caplog.records if "EMIT-LOST" in r.getMessage()]
    assert len(lost) == 1 and "TokensBridgeUnlocked" in lost[0] and "btx-2" in lost[0] and "k2" in lost[0] and "bridge.unlock" in lost[0] and "ConnectionError" in lost[0]
    if before >= 0:
        assert _count("TokensBridgeUnlocked") == before + 1


async def test_an_emit_that_exhausted_its_retries_is_the_same_failure(caplog):
    em = _Emitter(False)
    with caplog.at_level(logging.ERROR, logger=ee.logger.name):
        ok = await ee.emit_or_report(em, event_type="A2APaymentAuthorized", aggregate_id="did:x", data={})
    assert ok is False
    assert any("exhausted its retries" in r.getMessage() for r in caplog.records)


async def test_no_emitter_is_reported_not_raised(caplog):
    with caplog.at_level(logging.ERROR, logger=ee.logger.name):
        ok = await ee.emit_or_report(None, event_type="WrappedTokensMinted", aggregate_id="btx-3", data={})
    assert ok is False and any("no event emitter" in r.getMessage() for r in caplog.records)


async def test_the_background_wrapper_reports_a_lost_emit(caplog):
    em = object.__new__(ee.EventEmitter)

    async def _boom(**kw):
        raise TimeoutError("slow store")
    em.emit = _boom  # type: ignore[assignment]
    with caplog.at_level(logging.ERROR, logger=ee.logger.name):
        await ee.EventEmitter._emit_background_wrapper(em, event_type="TokensTransferred", aggregate_id="did:s", data={}, idempotency_key="xfer-1")
    lost = [r.getMessage() for r in caplog.records if "EMIT-LOST" in r.getMessage()]
    assert len(lost) == 1 and "TokensTransferred" in lost[0] and "xfer-1" in lost[0] and "emit_background" in lost[0]


NAMED_SITES = {
    ("routers/token_bridge.py", "TokensBridgeLocked"), ("routers/token_bridge.py", "WrappedTokensMinted"),
    ("routers/token_bridge.py", "TokensBridgeUnlocked"), ("routers/a2a_payment.py", "A2APaymentAuthorized"),
    ("services/teg_stream_proxy.py", "TokensTransferred"), ("services/teg_stream_proxy.py", "TransactionFeeCollected"),
}
KEYED_SITES = {
    ("routers/fiat_onramp.py", "FiatProviderSignatureFailed"), ("services/staking_rewards_service.py", "RewardsAutoCompoundSkipped"),
    ("services/federation_compliance_monitor.py", "TreasuryBankruptcyQuarantineTriggered"),
    ("services/federation_compliance_monitor.py", "TreasuryQuarantineLifted"),
    ("background_tasks/federation_sync.py", "PeerTrustActionApplied"), ("background_tasks/federation_sync.py", "PeerTrustActionObserved"),
}


@pytest.fixture(scope="module")
def rows():
    r = census._census()
    assert len(r) >= 300, "the census is looking in the wrong tree"
    return r


def test_the_six_value_sites_no_longer_swallow_their_failure(rows):
    by = {(r["file"], r["event"]): r for r in rows}
    for site in NAMED_SITES:
        assert site in by, f"{site} vanished from the census"
        assert not by[site]["swallowed"], f"{site} still swallows: {by[site]['swallowed']}"


def test_the_named_keyless_value_sites_carry_a_key(rows):
    by = {(r["file"], r["event"]): r for r in rows}
    for site in KEYED_SITES:
        assert site in by, f"{site} vanished from the census"
        assert by[site]["key_state"] != "keyless", f"{site} is still keyless"


def test_both_ratchets_read_at_or_under_their_baselines(rows):
    swallowed = sum(1 for r in rows if r["swallowed"])
    keyless = sum(1 for r in rows if r["key_state"] == "keyless")
    assert swallowed <= census._BASELINE_SWALLOWED, (swallowed, census._BASELINE_SWALLOWED)
    assert keyless <= census._BASELINE_NO_IDEMPOTENCY, (keyless, census._BASELINE_NO_IDEMPOTENCY)
