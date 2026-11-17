"""V0663 recut (order gwo_9c2f8be8a69c8fb97fc5c517; session-tester, room seq 3780): a discover page past the last row
answers the real total.

`GET /agent-cards/discover` took its total from the page's own rows (COUNT(*) OVER ()), so a page past the end, which
has no row, answered total 0 and has_more false while facets.total in the same answer held the real count (sbx-alpha:
?limit=4&offset=100000 gave total 0 beside facets.total 4063). An empty page now answers the population from the facets
it already reads for that request: their grand total, or with an origin filter the counts of the origins asked; has_more
false. A page inside the population keeps its window total.

The suite's ranked-page leg walked three pages of four whatever the population was, so a fresh pair with 4 cards read
totals [4, 0, 0] and waited for a population that would never settle. It now walks only the pages that fall inside the
population it read first, and records NOT MEASURED at once when fewer than two pages fit.
Red on v0663/cut b7ca684e9.
"""
from __future__ import annotations

import asyncio
import io
import json
import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import agent_cards as mod
from tests.test_discover_one_snapshot import KW, _row

FACETS = [{"origin": None, "count": 10, "live_24h": 2, "paid": 3},
          {"origin": "Local", "count": 7, "live_24h": 1, "paid": 2},
          {"origin": "peer-frame", "count": 3, "live_24h": 1, "paid": 1}]


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return None


class _Db:
    def __init__(self, page_rows):
        self.page_rows = page_rows

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        if "peer_registries" in sql:
            return _Res([])
        if "full_total" in sql:
            return _Res(self.page_rows)
        if "GROUPING SETS" in sql:
            return _Res([dict(f) for f in FACETS])
        if "jsonb_array_elements_text" in sql:
            return _Res([])
        return _Res([])


def _call(db, **over):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(mod.discover_agent_cards(db=db, **{**KW, **over}))
    finally:
        loop.close()


# --- the route -------------------------------------------------------------------------------------------------------

def test_a_page_past_the_end_answers_the_population():
    out = _call(_Db([]), limit=4, offset=100000)
    assert out["items"] == [] and out["has_more"] is False
    assert out["total"] == 10 == out["facets"]["total"]


def test_a_page_past_the_end_with_an_origin_filter_answers_that_origins_count():
    out = _call(_Db([]), limit=4, offset=100000, origins="peer-frame")
    assert out["items"] == [] and out["has_more"] is False and out["total"] == 3
    out = _call(_Db([]), limit=4, offset=100000, origins="PEER-FRAME,Local")
    assert out["total"] == 10, "the origins match as the page's filter does (lower-cased)"


def test_a_page_inside_the_population_keeps_its_window_total():
    out = _call(_Db([_row(full_total=6544)]), limit=4, offset=0)
    assert out["total"] == 6544 and out["has_more"] is True


def test_the_helper():
    assert mod._empty_page_total(FACETS, []) == 10
    assert mod._empty_page_total(FACETS, ["local"]) == 7
    assert mod._empty_page_total([], []) == 0


# --- the suite's ranked-page leg ---------------------------------------------------------------------------------------

from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet  # noqa: E402
from agentvault_registry.api_tests.federation_suite.tests import test_discovery_index_feed as feed  # noqa: E402


def _population(n):
    """A frame with `n` ranked cards, answering the discover route as the product now does."""
    calls = []

    def urlopen(req, timeout=None):
        url = urllib.parse.urlparse(req.full_url if hasattr(req, "full_url") else req)
        q = dict(urllib.parse.parse_qsl(url.query))
        calls.append(q)
        limit, offset = int(q.get("limit", 30)), int(q.get("offset", 0))
        ids = [f"c{i}" for i in range(n)][offset:offset + limit]
        body = {"items": [{"id": i} for i in ids], "total": n, "has_more": offset + len(ids) < n,
                "facets": {"total": n, "free": n, "paid": 0, "live_24h": 0, "origins": [{"name": "Local", "count": n}]}}

        class _R(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return _R(json.dumps(body).encode())
    return calls, urlopen


class _Rig:
    async def assert_within(self, budget_sec, predicate, description, capture_state=None):
        ok = await predicate()
        return SimpleNamespace(passed=ok, last_state=capture_state() if capture_state else None)


def test_a_population_too_small_for_two_pages_is_not_measured_at_once(monkeypatch):
    calls, urlopen = _population(4)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(PreconditionUnmet) as e:
        asyncio.run(feed.test_ranked_page_public_and_partitions(_Rig()))
    assert "4" in str(e.value) and len(calls) <= 2, "one read of the population, no waiting for it to settle"


def test_a_population_of_forty_walks_the_pages_inside_it(monkeypatch):
    calls, urlopen = _population(40)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    out = asyncio.run(feed.test_ranked_page_public_and_partitions(_Rig()))
    assert out.passed is True
    offsets = sorted({int(c.get("offset", 0)) for c in calls if c.get("limit") == "4" and "skip" not in c})
    assert offsets == [0, 4, 8]


def test_a_population_of_six_walks_two_pages(monkeypatch):
    calls, urlopen = _population(6)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    out = asyncio.run(feed.test_ranked_page_public_and_partitions(_Rig()))
    assert out.passed is True
    offsets = sorted({int(c.get("offset", 0)) for c in calls if c.get("limit") == "4" and "skip" not in c})
    assert offsets == [0, 4], "the third page (offset 8) falls outside a population of 6"
