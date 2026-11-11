"""/metrics does no database work (2026-11-07, session-watch).

WHY THIS EXISTS, measured on production the day it was written: `db.get_stats()`
is six full scans of an 11.9 GB `audit_history` (1,352,138 rows), and one of the
six walks rows backwards until a non-OK one appears — a streak that was 274,906
rows and grows by one every clean cycle. So the cost of rendering /metrics grows
WHILE THE INVARIANT HOLDS: 9-10 s in September 2026, 42.5 s in November. The
25 s scrape timeout was overtaken, `up{job="auditor"}` stuck at 0 from 15:49Z,
and auditor_delta, auditor_status and auditor_last_cycle_age_seconds had NO
series at all — which left every auditor_* alert blind, the supply-breach ones
included, while the auditor itself was reporting Δ=0 perfectly well.

The contract these tests pin:
  - /metrics never touches the database, whatever state the cache is in.
  - The two history gauges come from the cache or are LEFT OUT; nothing
    substitutes a zero for a number that was never measured.
  - auditor_stats_cache_age_seconds publishes the staleness, so a stale page is
    legible instead of silent.
  - /api/auditor/stats serves the same cache, and is the ONE reader allowed to
    compute a scope nobody has asked for yet (a person waits; a scraper cannot).
  - A refresh never overlaps another, and the floor keeps a 60 s audit cycle
    from holding a core on a query that takes tens of seconds.

Each test carries its own control, so none of them can pass by the value simply
never arriving. AUDITOR_TREE points the suite at another checkout (the base run).
"""
import asyncio
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture()
def main(tmp_path, monkeypatch):
    _purge()
    for k in list(os.environ):
        if k.endswith("_EVENT_STORE_URL") or k.endswith("_ES_DSN") or (k.startswith("AUDITOR_") and k != "AUDITOR_TREE"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
    monkeypatch.setenv("STATS_CACHE_MIN_INTERVAL_SEC", "300")
    monkeypatch.syspath_prepend(TREE)
    module = importlib.import_module("src.auditor.main")
    module._stats_cache.clear()
    module._stats_cache_at.clear()
    yield module
    _purge()


def _forbid_queries(main, monkeypatch):
    """Patch the query out and hand back a proof that the patch is live."""
    calls = []

    async def stats(frame=None, frames=None, with_streak=True):
        calls.append((frame, tuple(frames) if frames else None))
        raise AssertionError("the database was queried")

    monkeypatch.setattr(main.db, "get_stats", stats)
    return calls


def _counting_queries(main, monkeypatch, value=None):
    calls = []

    async def stats(frame=None, frames=None, with_streak=True):
        calls.append((frame, tuple(frames) if frames else None))
        out = dict(value or {"total_audits": 7, "uptime_pct": 99.5})
        # The real query answers None for the streak when it is told to skip the
        # backward walk, and that None must never be read as a streak of zero.
        out["consecutive_ok"] = out.get("consecutive_ok", 11) if with_streak else None
        return out

    monkeypatch.setattr(main.db, "get_stats", stats)
    return calls


def _streak_queries(main, monkeypatch, cold=11):
    """Records whether each call was asked to WALK the streak or to skip it."""
    seen = []

    async def stats(frame=None, frames=None, with_streak=True):
        seen.append(with_streak)
        return {"total_audits": 100, "uptime_pct": 99.0,
                "consecutive_ok": cold if with_streak else None}

    monkeypatch.setattr(main.db, "get_stats", stats)
    return seen


def _row(status="OK", atomic="OK", maintenance=0):
    return {"status": status, "atomic_status": atomic, "maintenance": maintenance}


def test_red_metrics_does_no_database_work_with_an_empty_cache(main, monkeypatch):
    calls = _forbid_queries(main, monkeypatch)

    text = asyncio.run(main.metrics()).body.decode()

    assert calls == [], "/metrics queried the database"
    # Nothing was measured, so nothing is published for it — no zero stands in.
    assert not any(l.startswith("auditor_total_audits") for l in text.splitlines())
    assert not any(l.startswith("auditor_uptime_pct") for l in text.splitlines())
    assert not any(l.startswith("auditor_stats_cache_age_seconds ") for l in text.splitlines())
    # THE CONTROL: the patch really does raise, so the silence above is the
    # route's behaviour and not a dead probe.
    with pytest.raises(AssertionError, match="the database was queried"):
        asyncio.run(main._compute_stats_into_cache())
    assert calls == [(None, None)]


def test_red_metrics_publishes_the_cached_history_and_its_age(main, monkeypatch):
    _forbid_queries(main, monkeypatch)
    main._stats_cache["all"] = {"total_audits": 1352138, "uptime_pct": 77.72}
    main._stats_cache_at["all"] = main.time.time() - 42.0

    text = asyncio.run(main.metrics()).body.decode()

    assert "auditor_total_audits 1352138" in text
    assert "auditor_uptime_pct 77.72" in text
    age = [l for l in text.splitlines() if l.startswith("auditor_stats_cache_age_seconds ")]
    assert len(age) == 1
    assert 40.0 <= float(age[0].split()[1]) <= 120.0


def test_red_the_stats_endpoint_serves_the_cache_without_querying(main, monkeypatch):
    calls = _forbid_queries(main, monkeypatch)
    main._stats_cache["all"] = {"total_audits": 3, "uptime_pct": 100.0}
    main._stats_cache_at["all"] = main.time.time()

    # Naming both arguments is load-bearing: calling the endpoint function
    # directly hands it the Query(...) DEFAULT object, and `if mode` on that
    # object is True, which would send this down the cold-scope path.
    assert asyncio.run(main.api_stats(frame=None, mode=None))["total_audits"] == 3
    assert calls == []


def test_red_a_cold_scope_is_computed_once_and_served_from_the_cache_after(main, monkeypatch):
    calls = _counting_queries(main, monkeypatch)

    first = asyncio.run(main.api_stats(frame="eu", mode=None))
    second = asyncio.run(main.api_stats(frame="eu", mode=None))

    assert first == second
    assert calls == [("eu", None)], "a cold scope must be computed exactly once"
    # THE CONTROL: a DIFFERENT cold scope still costs its one query, so the
    # single call above is the cache working and not the fake refusing to run.
    asyncio.run(main.api_stats(frame="asia", mode=None))
    assert calls == [("eu", None), ("asia", None)]


def test_red_the_refresh_floor_skips_a_scope_that_is_still_fresh(main, monkeypatch):
    calls = _counting_queries(main, monkeypatch)
    main._stats_cache["all"] = {"total_audits": 1, "uptime_pct": 100.0}
    main._stats_cache_at["all"] = main.time.time()      # just computed

    asyncio.run(main.refresh_stats_cache())
    assert calls == [], "a fresh scope was recomputed inside the floor"

    # THE CONTROL: force ignores the floor, and so does an aged value.
    asyncio.run(main.refresh_stats_cache(force=True))
    assert calls == [(None, None)]
    main._stats_cache_at["all"] = main.time.time() - 10_000
    asyncio.run(main.refresh_stats_cache())
    assert len(calls) == 2


def test_red_a_refresh_never_overlaps_another(main, monkeypatch):
    calls = _counting_queries(main, monkeypatch)

    async def drive():
        await main._stats_refresh_lock.acquire()
        try:
            await main.refresh_stats_cache(force=True)   # must return at once
        finally:
            main._stats_refresh_lock.release()
        # THE CONTROL: with the lock free, the same call does the work.
        await main.refresh_stats_cache(force=True)

    asyncio.run(drive())
    assert calls == [(None, None)], "a second pass ran while one was in flight"


def test_red_a_failed_refresh_keeps_the_previous_value_and_does_not_raise(main, monkeypatch):
    main._stats_cache["all"] = {"total_audits": 5, "uptime_pct": 100.0}
    main._stats_cache_at["all"] = main.time.time() - 10_000
    _forbid_queries(main, monkeypatch)

    asyncio.run(main.refresh_stats_cache())             # must not raise

    assert main.cached_stats()["total_audits"] == 5
    # The age is the OLD stamp: a failed refresh must not look like a fresh one.
    assert main.cached_stats_age() > 1000


# ── the streak: read once, then carried by the rows ──────────────────────


def test_red_the_streak_is_walked_once_and_carried_after(main, monkeypatch):
    seen = _streak_queries(main, monkeypatch, cold=274906)

    asyncio.run(main._compute_stats_into_cache())
    assert seen == [True], "the cold read must walk the streak"
    assert main.cached_stats()["consecutive_ok"] == 274906

    main.note_audit_row("eu", _row())
    assert main.cached_stats()["consecutive_ok"] == 274907

    asyncio.run(main.refresh_stats_cache(force=True))
    assert seen == [True, False], "a refresh must not walk the streak again"
    # The carried value survives the refresh, and the None the query answered
    # for a skipped walk never reaches the cache.
    assert main.cached_stats()["consecutive_ok"] == 274907


def test_red_a_row_that_is_not_clean_resets_the_streak(main, monkeypatch):
    _streak_queries(main, monkeypatch, cold=5)
    asyncio.run(main._compute_stats_into_cache())

    main.note_audit_row("eu", _row(status="BREACH", atomic="BREACH"))
    assert main.cached_stats()["consecutive_ok"] == 0
    main.note_audit_row("eu", _row())
    assert main.cached_stats()["consecutive_ok"] == 1


def test_red_the_predicate_is_the_databases_own_so_maintenance_counts_as_clean(main, monkeypatch):
    _streak_queries(main, monkeypatch, cold=3)
    asyncio.run(main._compute_stats_into_cache())

    # db.counts_ok treats a maintenance row as OK, and OK_SQL on the row does
    # the same; using that one predicate is what keeps the carried streak and a
    # cold read of the database from disagreeing.
    main.note_audit_row("eu", _row(status="BREACH", atomic="BREACH", maintenance=1))
    assert main.cached_stats()["consecutive_ok"] == 4
    assert main.db.counts_ok("BREACH", "BREACH", 1) is True


def test_red_a_row_moves_only_the_scopes_that_cover_its_frame(main, monkeypatch):
    _streak_queries(main, monkeypatch, cold=10)
    asyncio.run(main._compute_stats_into_cache())                                  # "all"
    asyncio.run(main._compute_stats_into_cache(frame="eu"))                        # "frame:eu"
    asyncio.run(main._compute_stats_into_cache(frames=["asia", "frame-a"]))        # "frames:asia,frame-a"

    main.note_audit_row("eu", _row())

    assert main.cached_stats()["consecutive_ok"] == 11                             # all: covered
    assert main.cached_stats(frame="eu")["consecutive_ok"] == 11                   # its own frame
    assert main.cached_stats(frames=["asia", "frame-a"])["consecutive_ok"] == 10   # untouched
    # THE CONTROL: a frame inside that list does move it, so the assertion above
    # is about coverage and not about the helper doing nothing.
    main.note_audit_row("asia", _row())
    assert main.cached_stats(frames=["asia", "frame-a"])["consecutive_ok"] == 11
    assert main.cached_stats(frame="eu")["consecutive_ok"] == 11


def test_red_a_scope_with_no_cold_read_is_not_invented_from_rows(main, monkeypatch):
    _streak_queries(main, monkeypatch, cold=10)

    # No cold read has happened, so there is no streak to carry and none is
    # manufactured: a count that started mid-history would be a fiction.
    main.note_audit_row("eu", _row())
    assert main.cached_stats() is None
    assert main._stats_streak == {}
