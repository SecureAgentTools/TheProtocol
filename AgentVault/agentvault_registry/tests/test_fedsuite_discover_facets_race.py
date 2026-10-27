"""V0614 (agentvault2-5b): the ranked discovery page's facet check, under a population that moves.

`discovery_ranked_page_is_public_and_partitions` failed CRITICAL in the V0613 MCP tester round (and on the 2026-10-13
nightly) on "facet facets_total=6542 disagrees with total=6544". The route counts the page's total and the facets in
two statements, each its own READ COMMITTED snapshot, so a card landing between them makes one answer disagree with
itself; the sign flipped between the two reds (timing, not a filter). The check now reads the page once more on a
mismatch: the total moved -> not measurable this pass (PreconditionUnmet); the total held and the answer still
disagrees with itself -> red; the second answer agrees -> it is the one judged. And the rig's red detail names what the
LAST attempt did, never an earlier attempt's exception as if it were the reason.
"""
from __future__ import annotations

import asyncio
import io
import json
import urllib.parse
import urllib.request

import pytest

from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, FederationTestRig, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_discovery_index_feed as T


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


IDS = [f"card-{i:02d}" for i in range(12)]


def _page(total, facets_total, ids):
    return {"items": [{"id": i} for i in ids], "total": total, "has_more": True, "generated_in_ms": 5,
            "facets": {"total": facets_total, "free": facets_total, "paid": 0, "live_24h": 1,
                       "origins": [{"origin": "local", "count": facets_total}]}}


class _Answer(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, wholes):
    """Each read of the whole page (limit=12) takes the next answer from `wholes`; the walk's pages and the skip probe
    are cut from the LAST whole answer served, with its total, so a walk agrees with what was read before it."""
    seen = {"whole": 0, "paths": []}
    last = {"p": None}

    def urlopen(req, timeout=None):
        u = urllib.parse.urlparse(req.full_url)
        q = urllib.parse.parse_qs(u.query)
        seen["paths"].append(u.path + "?" + u.query)
        limit = int(q["limit"][0])
        if limit == 12:
            last["p"] = wholes[min(seen["whole"], len(wholes) - 1)]
            seen["whole"] += 1
            body = last["p"]
        else:
            off = int((q.get("offset") or q.get("skip") or ["0"])[0]) if "offset" in q else 0
            p = last["p"]
            body = {"items": p["items"][off:off + limit], "total": p["total"], "has_more": True}
        return _Answer(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return seen


class _OneAttemptRig:
    """assert_within that runs the predicate ONCE: the predicate's own judgement, with its exceptions escaping."""

    async def assert_within(self, *, budget_sec, predicate, description, poll_interval_sec=1.0, capture_state=None):
        ok = await predicate()
        return AssertionResult(passed=bool(ok), description=description, budget_sec=budget_sec, elapsed_sec=0.0,
                               polling_attempts=1, last_state=capture_state() if capture_state else None)


def _run():
    return asyncio.run(T.test_ranked_page_public_and_partitions(_OneAttemptRig()))


def test_agreeing_facets_are_read_once_and_the_partition_is_judged(monkeypatch):
    seen = _serve(monkeypatch, [_page(100, 100, IDS)])
    r = _run()
    assert r.passed, r.last_state
    assert seen["whole"] == 2   # the read the facets are judged on + the walk's own larger read (V0615: read with the pages)


def test_a_mismatch_while_the_population_moves_is_not_measured(monkeypatch):
    _serve(monkeypatch, [_page(100, 99, IDS), _page(101, 101, IDS)])
    with pytest.raises(PreconditionUnmet) as e:
        _run()
    assert "while the population moved (100 → 101)" in str(e.value) and "Not a defect" in str(e.value)


def test_a_mismatch_with_the_population_still_is_red(monkeypatch):
    _serve(monkeypatch, [_page(100, 99, IDS), _page(100, 99, IDS)])
    r = _run()
    assert r.passed is False
    assert "in two reads with the population still at 100" in r.last_state["why"], r.last_state


def test_a_mismatch_that_settles_on_the_second_read_is_judged_on_it(monkeypatch):
    seen = _serve(monkeypatch, [_page(100, 99, IDS), _page(100, 100, IDS)])
    r = _run()
    assert r.passed, r.last_state
    assert seen["whole"] == 3 and r.last_state["facet_checks"]["facets_total"] == 100   # 2 facet reads + the walk's


def test_the_last_attempt_names_its_own_reason_not_an_earlier_exception():
    rig = object.__new__(FederationTestRig)   # assert_within reads nothing from the instance
    state, calls = {}, {"n": 0}

    async def pred():
        calls["n"] += 1
        state.pop("why", None)
        if calls["n"] == 1:
            raise PreconditionUnmet("the population moved; not a defect")
        state["why"] = "facet facets_total=9 disagrees with total=10"
        return False

    r = asyncio.run(rig.assert_within(budget_sec=0.3, predicate=pred, description="x", poll_interval_sec=0.05,
                                      capture_state=lambda: state))
    assert r.passed is False
    d = r.failure_detail or ""
    assert d.startswith("budget 0.3s exhausted after"), d
    assert "the last attempt returned False" in d and "an earlier attempt raised PreconditionUnmet" in d, d
    assert d.endswith("why: facet facets_total=9 disagrees with total=10"), d
    assert "last_exception=" not in d, d
