"""§MCPTEST30 (2026-09-30) — the paging partition is measured on the WINDOW it walks, not on the whole tail.

`discovery_feed_paging_is_a_partition` walks the index feed ASC from an instant several cards share and compares
four pages of four with one call of sixteen. It refused (NOT MEASURED) whenever the feed's `total` changed during the
walk, and `total` counts every card at or after the anchor: on a tier with the live AGORA sim that tail moves every
minute, so 29 of 50 archived federation runs ended NOT MEASURED there although a card past row sixteen cannot touch
the first sixteen. The test now reads the window again after the walk and refuses only when the window itself moved.

Offline, against an in-memory feed ordered like the real one ((updated_at, id) ASC, inclusive cursor): tail churn is
measured and reported; a card leaving the window is still NOT MEASURED; a non-total order (the defect the test exists
for) still fails on a window that did not move.
"""
from __future__ import annotations

import asyncio
import urllib.parse

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R
from agentvault_registry.api_tests.federation_suite.tests import test_discovery_index_feed as DI

# Twenty cards. c00/c01 share the oldest instant (the anchor the test looks for); c03/c04 share another one, at
# positions 3 and 4 of the window, i.e. across the boundary between the first and the second page of four.
_T0, _T1, _T2 = "2026-09-30T10:00:00+00:00", "2026-09-30T10:01:00+00:00", "2026-09-30T10:02:00+00:00"
_T = [_T0, _T0, _T1, _T2, _T2] + [f"2026-09-30T10:{m:02d}:00+00:00" for m in range(3, 18)]


def _later(n):
    return f"2026-09-30T11:{n:02d}:00+00:00"


class Feed:
    """The index feed: GET /api/v1/agent-cards/?limit=&skip=&updated_since= (inclusive), ordered (updated_at, id).
    `after_call(n, feed)` runs after the n-th answer, so a scenario can move the population mid-walk; `tie_order`
    lets a scenario arrange equal sort keys per call (a non-total ORDER BY)."""

    def __init__(self, after_call=None, tie_order=None):
        self.cards = [{"id": f"c{i:02d}", "updated_at": t} for i, t in enumerate(_T)]
        self.calls = 0
        self.after_call = after_call
        self.tie_order = tie_order

    def answer(self, path):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(path).query))
        rows = sorted(self.cards, key=lambda c: (c["updated_at"], c["id"]))
        if "updated_since" in q:
            rows = [c for c in rows if c["updated_at"] >= q["updated_since"]]
        total = len(rows)
        limit, skip = int(q.get("limit", 50)), int(q.get("skip", 0))
        if self.tie_order:
            rows = self.tie_order(rows, limit, skip)
        page = [dict(c) for c in rows[skip:skip + limit]]
        self.calls += 1
        if self.after_call:
            self.after_call(self.calls, self)
        return 200, {"items": page, "pagination": {"total_items": total}}


class OneAttemptRig(R.FederationTestRig):
    """The real assert_within with no budget: one attempt, then its own verdict rules (a precondition the last
    attempt raised is re-raised; anything else is a pass or a failure with the captured state)."""

    async def assert_within(self, *, budget_sec, predicate, description, poll_interval_sec=1.0, capture_state=None):
        return await super().assert_within(budget_sec=0.0, predicate=predicate, description=description,
                                           poll_interval_sec=0.0, capture_state=capture_state)


def _run(monkeypatch, feed):
    async def fake_rest(rig, method, path, label=None, **kw):
        assert method == "GET" and path.startswith(DI._FEED), path
        return feed.answer(path)
    monkeypatch.setattr(DI, "_rest", fake_rest)
    return asyncio.run(DI.test_paging_is_a_partition(OneAttemptRig()))


def test_a_stable_feed_is_a_partition(monkeypatch):
    r = _run(monkeypatch, Feed())
    assert r.passed, r.last_state
    assert r.last_state["walked"] == 16 and r.last_state["distinct"] == 16
    assert r.last_state["tail_churn_during_walk"] is False


def test_tail_churn_is_measured_and_reported_not_refused(monkeypatch):
    """The round 2 shape (267 -> 266): the tail moves during the walk, the first sixteen rows do not.
    Calls: 1 the scan, 2 the window, 3-6 the pages, 7 the window again."""
    def churn(n, feed):
        if n == 3:
            feed.cards = [c for c in feed.cards if c["id"] != "c19"]           # the newest card leaves
        if n == 4:
            feed.cards += [{"id": "new1", "updated_at": _later(1)}, {"id": "new2", "updated_at": _later(2)}]
    r = _run(monkeypatch, Feed(after_call=churn))
    assert r.passed, r.last_state
    assert r.last_state["tail_churn_during_walk"] is True
    assert r.last_state["totals_during_walk"][0] == 20 and 19 in r.last_state["totals_during_walk"]


def test_a_card_leaving_the_window_is_not_measured(monkeypatch):
    """An existing card INSIDE the window is updated mid-walk (its instant moves to now): rows shift under the pages,
    so the walk cannot be judged either way. NOT MEASURED, naming how many left and entered."""
    def touch(n, feed):
        if n == 3:
            next(c for c in feed.cards if c["id"] == "c05")["updated_at"] = _later(30)
    with pytest.raises(R.PreconditionUnmet, match="a card inside the walked window changed under the walk"):
        _run(monkeypatch, Feed(after_call=touch))


def test_a_non_total_order_still_fails_on_a_window_that_did_not_move(monkeypatch):
    """The defect the test exists for (findings row 85): equal sort keys arranged differently per plan. The first page
    puts c03 before c04, the second the other way round, so c03 is read twice and c04 never; the window call and its
    re-read agree with each other. A FAILURE, with the duplicate and the miss named."""
    def unstable(rows, limit, skip):
        if limit == 4 and skip == 4:
            i, j = next(k for k, c in enumerate(rows) if c["id"] == "c03"), next(k for k, c in enumerate(rows) if c["id"] == "c04")
            rows = list(rows)
            rows[i], rows[j] = rows[j], rows[i]
        return rows
    r = _run(monkeypatch, Feed(tie_order=unstable))
    assert not r.passed
    assert r.last_state["duplicates"] == ["c03"] and r.last_state["missed"] == ["c04"], r.last_state


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    """asyncio.run() closes its loop and leaves none current; a later file's sync test calling get_event_loop()
    would then fail far from here (memory: a test that calls asyncio.run leaves the next file without a loop)."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
