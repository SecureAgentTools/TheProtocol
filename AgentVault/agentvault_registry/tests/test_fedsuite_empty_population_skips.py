"""§TESTBED (2026-09-19): federation-suite checks whose subject is a POPULATION skip by name when it is absent.

Measured in a fresh kit sandbox: a young ledger (60 events), no developer signing key yet and no guild order were each
reported red, which reads as a broken store, a broken JWKS and a broken guild. They are coverage holes: a named skip,
counted against the pass rate, never a pass. With the population present the checks still judge it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_event_store_recent_event_types as es
from agentvault_registry.api_tests.federation_suite.tests import test_federation_card_pull_sync_etag as jw


class _Rig:
    def __init__(self, answer):
        self.answer = answer

    def mcp(self, _label):
        rig = self

        class _C:
            async def call(self, _tool, *_a, **_k):
                return rig.answer
        return _C()

    async def assert_within(self, *, budget_sec, predicate, description, capture_state=None, **_k):
        ok = bool(await predicate())
        return AssertionResult(passed=ok, description=description, budget_sec=budget_sec, elapsed_sec=0.0,
                               polling_attempts=1, last_state=capture_state() if capture_state else None)


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


async def test_a_young_ledger_is_not_measured():
    with pytest.raises(PreconditionUnmet) as exc:
        await es.test_eventstore_stats(_Rig({"total_events": 60, "newest_event": _ago(minutes=5), "oldest_event": _ago(hours=1)}))
    assert "young ledger (60 events)" in str(exc.value)


async def test_an_old_ledger_below_the_floor_still_fails():
    """§NIGHTLYTRUTH's gate, from the young ledger's side: a store that has run for weeks and holds 500 events has lost its
    population, and a store that reports no age cannot be called young (test_nightlytruth_gates_report_not_gate.py)."""
    res = await es.test_eventstore_stats(_Rig({"total_events": 500, "newest_event": _ago(minutes=5), "oldest_event": _ago(days=30)}))
    assert res.passed is False
    res = await es.test_eventstore_stats(_Rig({"total_events": 500, "newest_event": _ago(minutes=5)}))
    assert res.passed is False


async def test_a_grown_ledger_is_judged():
    res = await es.test_eventstore_stats(_Rig({"total_events": 64491, "newest_event": "2026-09-19T15:50:20+00:00"}))
    assert res.passed is True


async def test_no_developer_key_yet_is_not_measured():
    with pytest.raises(PreconditionUnmet):
        await jw.test_jwks_ed25519(_Rig({"keys": []}))


async def test_published_keys_are_judged():
    ok = await jw.test_jwks_ed25519(_Rig({"keys": [{"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "kid": "k1"}]}))
    assert ok.passed is True
    bad = await jw.test_jwks_ed25519(_Rig({"keys": [{"kty": "EC", "crv": "P-256", "alg": "ES256", "kid": "k2"}]}))
    assert bad.passed is False   # keys present, none EdDSA: a finding, not a skip
