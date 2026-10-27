"""V0615 (agentvault2-09, the MCP tester lane): two federation-suite instruments that skipped on a busy tier.

The V0614 MCP tester round (2026-10-14 16:17Z) measured no defect and skipped three checks the tier could have answered:
- `discovery_ranked_page_is_public_and_partitions`: its walk read the larger page and three offset pages one after
  another, and the suite's own sibling tests create agents throughout, so the population moved (6571 -> 6572) under
  every walk for the whole 60 s budget. The walk's four reads now go out together and must report one total.
- `agent_card_pull_sync_alpha_sees_parent_agent` and `agent_card_federation_pull_sync_works`: the subject (an agent
  older than one 6 h pull cycle) was looked for in discoverAgents' first 50 rows only, the NEWEST; after a day of suite
  runs all 50 were younger. The rig's propagated_subject reads on, page by page, until an eligible subject turns up.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import threading
import urllib.parse
import urllib.request

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R
from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_discovery_index_feed as T


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


IDS = [f"card-{i:02d}" for i in range(12)]


def _whole(total):
    return {"items": [{"id": i} for i in IDS], "total": total, "has_more": True, "generated_in_ms": 5,
            "facets": {"total": total, "free": total, "paid": 0, "live_24h": 1,
                       "origins": [{"origin": "local", "count": total}]}}


class _Answer(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _OneAttemptRig:
    async def assert_within(self, *, budget_sec, predicate, description, poll_interval_sec=1.0, capture_state=None):
        ok = await predicate()
        return AssertionResult(passed=bool(ok), description=description, budget_sec=budget_sec, elapsed_sec=0.0,
                               polling_attempts=1, last_state=capture_state() if capture_state else None)


def _serve(monkeypatch, *, total=100, page_total=None, barrier=None):
    """The first larger read (the facets' read) answers at once; every later read of the walk (the larger one and the
    three offset pages) waits at `barrier` when one is given, so a walk that reads one after another never gets past
    it. The undeclared-skip probe after the walk never waits. Pages carry `page_total` when given (a population that
    moved between the walk's reads)."""
    seen = {"whole": 0, "pages": 0, "broken": 0}
    lock = threading.Lock()

    def urlopen(req, timeout=None):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        limit = int(q["limit"][0])
        with lock:
            first = limit == 12 and seen["whole"] == 0
            seen["whole" if limit == 12 else "pages"] += 1
        if barrier is not None and not first and "skip" not in q:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                seen["broken"] += 1
                raise
        if limit == 12:
            body = _whole(total)
        else:
            off = int(q["offset"][0]) if "offset" in q else 0
            body = {"items": [{"id": i} for i in IDS[off:off + limit]],
                    "total": total if page_total is None else page_total, "has_more": True}
        return _Answer(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return seen


def _run():
    return asyncio.run(T.test_ranked_page_public_and_partitions(_OneAttemptRig()))


def test_the_walks_four_reads_are_in_flight_together(monkeypatch):
    seen = _serve(monkeypatch, barrier=threading.Barrier(4, timeout=5))
    r = _run()
    assert r.passed, r.last_state
    assert seen["broken"] == 0 and seen["whole"] == 2, seen
    assert r.last_state["walk_total"] == 100 and r.last_state["walked"] == 12 and r.last_state["distinct"] == 12


def test_control_a_barrier_of_five_cannot_be_met_by_four_reads(monkeypatch):
    """The barrier proves concurrency only if it can fail: five parties, four reads, so every walk read breaks it."""
    seen = _serve(monkeypatch, barrier=threading.Barrier(5, timeout=0.5))
    r = _run()
    assert r.passed is False and seen["broken"] >= 1, (seen, r.last_state)


def test_a_walk_whose_reads_report_two_totals_is_not_measured(monkeypatch):
    _serve(monkeypatch, total=100, page_total=101)
    with pytest.raises(PreconditionUnmet) as e:
        _run()
    assert "the ranked population changed under the walk (100 → [101, 101, 101] across four concurrent reads)" in str(
        e.value) and "Not a defect" in str(e.value)


# ─── propagated_subject: past the first page when it holds only young agents ───────────────────────────────────────


def _agent(i, age_h, name="agent"):
    created = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=age_h)).isoformat()
    return {"did": f"did:theprotocol:{i:04d}", "name": f"{name}-{i}", "created_at": created}


class _FakeMcp:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def call(self, tool, args):
        assert tool == "discoverAgents"
        self.calls.append(dict(args))
        o, n = args.get("offset", 0), args["limit"]
        return {"agents": self.rows[o:o + n], "total": len(self.rows)}


class _FakeRig:
    def __init__(self, rows):
        self.client = _FakeMcp(rows)

    def mcp(self, label):
        assert label == "sandbox-A"
        return self.client


def _subject(rows, **kw):
    rig = _FakeRig(rows)
    return asyncio.run(R.propagated_subject(rig, "sandbox-A", **kw)), rig.client.calls


def test_a_subject_one_page_down_is_found():
    rows = [_agent(i, 1) for i in range(50)] + [_agent(50 + i, 30) for i in range(50)]
    (did, age, eligible, seen), calls = _subject(rows)
    assert did and age > 6 * 3600 and eligible == 50 and seen == 100, (did, age, eligible, seen)
    assert [c["offset"] for c in calls] == [0, 50]


def test_control_one_page_only_finds_none_on_the_same_rows():
    rows = [_agent(i, 1) for i in range(50)] + [_agent(50 + i, 30) for i in range(50)]
    (did, _, eligible, seen), calls = _subject(rows, pages=1)
    assert did == "" and eligible == 0 and seen == 50 and len(calls) == 1


def test_the_first_page_is_enough_when_it_holds_a_subject_and_a_canary_wins():
    rows = [_agent(0, 10), _agent(1, 40, name="canary")] + [_agent(2 + i, 1) for i in range(48)] + [_agent(99, 99)]
    (did, _, eligible, seen), calls = _subject(rows)
    assert did == "did:theprotocol:0001" and eligible == 2 and seen == 50 and len(calls) == 1


def test_a_short_page_ends_the_read_and_nothing_old_is_none():
    rows = [_agent(i, 1) for i in range(70)]
    (did, _, eligible, seen), calls = _subject(rows)
    assert did == "" and eligible == 0 and seen == 70 and [c["offset"] for c in calls] == [0, 50]


def test_the_read_stops_at_its_page_cap():
    rows = [_agent(i, 1) for i in range(1000)]
    (did, _, _, seen), calls = _subject(rows, pages=6)
    assert did == "" and seen == 300 and len(calls) == 6
