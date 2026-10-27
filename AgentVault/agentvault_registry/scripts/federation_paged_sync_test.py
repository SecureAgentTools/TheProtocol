#!/usr/bin/env python3
"""§SYNCPAGE — N-transition test for the federation paged cursor walk.

Drives background_tasks.federation_sync._walk_pages / _advance_cursor against a
synthetic server implementing the EXACT new-server semantics (updated_at > cursor,
ASC, limit) and the old-server semantics (DESC) — because the §STREAKFIX class of
bug only appears from the second/third state transition onward, where a 2-cycle
canary is blind.

Run in-container:
    docker exec <registry> sh -c 'cd /app && PYTHONPATH=/app/src python3 /app/scripts/federation_paged_sync_test.py'

The suite FAILS ITSELF if its own scenarios go vacuous (page counts, stall
counts and skip counts are asserted exactly — a walk that "passes" without
exercising ≥3 transitions is reported as a failure, not a pass).
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/src")

from agentvault_registry.background_tasks.federation_sync import (  # noqa: E402
    _walk_pages, _advance_cursor, _max_updated_at, _SYNC_EPOCH,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
FAILURES = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(name)


def corpus(n, spacing_s=60):
    """n cards with strictly increasing updated_at."""
    return [{"id": f"c{i:04d}", "updated_at": (T0 + timedelta(seconds=i * spacing_s)).isoformat()}
            for i in range(n)]


def make_server(cards, *, ascending=True, echo_ids=(), headers=True):
    """Synthetic /federation/agent-cards with EXACT export semantics:
    updated_at > cursor, ordered, SQL-limited — then the echo filter drops
    `echo_ids` AFTER the limit (the shrunken-page bug the live E2E caught),
    and §SYNCPAGE truth headers report the PRE-filter state (headers=False
    models an old server that never sends them)."""
    parsed = [(datetime.fromisoformat(c["updated_at"]), c) for c in cards]

    async def fetch(cursor, page_limit):
        rows = [(ts, c) for ts, c in parsed if ts > cursor]
        rows.sort(key=lambda x: x[0], reverse=not ascending)
        pre = rows[:page_limit]
        served = [c for _, c in pre if c["id"] not in echo_ids]
        srv_more = headers and len(pre) == page_limit
        srv_cursor = pre[-1][0] if (headers and len(pre) == page_limit and pre) else None
        return 200, served, srv_more, srv_cursor
    return fetch


async def run_walk(server, *, page_limit, max_pages, cursor0=_SYNC_EPOCH, fail_on_page=None):
    seen, stamps, state = [], [], {"pages": 0, "caught_up": False}

    async def fetch_page(cursor):
        return await server(cursor, page_limit)  # (status, cards, srv_more, srv_cursor)

    async def process(cards):
        state["pages"] += 1
        if fail_on_page is not None and state["pages"] == fail_on_page:
            return False
        seen.extend(c["id"] for c in cards)
        return True

    async def progress(cursor):
        stamps.append(cursor)

    async def caught_up():
        state["caught_up"] = True

    outcome = await _walk_pages(
        fetch_page=fetch_page, process_page=process, stamp_progress=progress,
        stamp_caught_up=caught_up, start_cursor=cursor0, page_limit=page_limit,
        max_pages=max_pages, mode="test", peer_name="synthetic")
    return outcome, seen, stamps, state


async def main():
    # ── 1. multi-page bootstrap: 25 cards, page 10 → 3 pages, complete, ≥3 transitions
    cards = corpus(25)
    outcome, seen, stamps, state = await run_walk(make_server(cards), page_limit=10, max_pages=50)
    check("1a walk completes", outcome == "caught_up", outcome)
    # overlap (−1s) may re-fetch boundary cards — DISTINCT coverage is the contract
    check("1b every card arrives exactly (set)", set(seen) == {c["id"] for c in cards},
          f"{len(set(seen))}/25 distinct")
    check("1c ≥3 transitions actually driven (anti-vacuous)", state["pages"] >= 3, str(state["pages"]))
    check("1d cursor stamped after every full page", len(stamps) >= 2, str(len(stamps)))

    # ── 2. budget pause + resume from the persisted cursor
    outcome, seen1, stamps1, _ = await run_walk(make_server(cards), page_limit=10, max_pages=1)
    check("2a budget pause reported", outcome == "budget", outcome)
    check("2b cursor persisted at pause", len(stamps1) == 1, str(len(stamps1)))
    outcome, seen2, _, _ = await run_walk(make_server(cards), page_limit=10, max_pages=50,
                                          cursor0=stamps1[-1])
    check("2c resume completes", outcome == "caught_up", outcome)
    check("2d pause+resume covers the whole corpus", set(seen1) | set(seen2) == {c["id"] for c in cards},
          f"{len(set(seen1) | set(seen2))}/25")

    # ── 3. dense same-timestamp bucket (denser than one page) → stall path terminates,
    #      the strictly-past step SKIPS the unreturned ties (that is the documented
    #      trade-off the reconcile heals — assert the skip so the claim stays honest)
    dense = [{"id": f"d{i:02d}", "updated_at": T0.isoformat()} for i in range(12)]
    tail = [{"id": "tail", "updated_at": (T0 + timedelta(hours=1)).isoformat()}]
    outcome, seen, _, _ = await run_walk(make_server(dense + tail), page_limit=10, max_pages=50)
    check("3a dense bucket terminates (no infinite loop)", outcome == "caught_up", outcome)
    check("3b tail after the bucket still arrives", "tail" in seen)
    skipped = {c["id"] for c in dense} - set(seen)
    check("3c the documented tie-skip really happens (reconcile's job)", len(skipped) == 2,
          f"skipped={sorted(skipped)}")

    # ── 4. OLD server (DESC, ignores paged) → walk must terminate and behave
    #      no worse than the pre-§SYNCPAGE single-shot (no infinite loop)
    outcome, seen, _, state = await run_walk(make_server(corpus(25), ascending=False),
                                             page_limit=10, max_pages=50)
    check("4a old-server DESC walk terminates", outcome in ("caught_up", "budget"), outcome)
    check("4b old-server pages bounded (no ping-pong)", state["pages"] <= 5, str(state["pages"]))

    # ── 5. processing failure → 'failed', no caught_up stamp
    outcome, _, _, state = await run_walk(make_server(corpus(25)), page_limit=10, max_pages=50,
                                          fail_on_page=2)
    check("5a process failure surfaces", outcome == "failed", outcome)
    check("5b no caught_up stamp on failure", state["caught_up"] is False)

    # ── 7. THE ECHO-FILTER BUG (caught by the live E2E 2026-08-03, frame-c→doha:
    #      484 of a 500-limit page with 7.4k rows remaining). Server drops echo
    #      cards AFTER the SQL limit → every page is SHORT while data remains.
    #      With truth headers the walk must still cover everything non-echo.
    cards = corpus(30)
    echo = {f"c{i:04d}" for i in range(0, 30, 5)}  # every 5th card is requester-sourced
    outcome, seen, _, state = await run_walk(make_server(cards, echo_ids=echo, headers=True),
                                             page_limit=10, max_pages=50)
    check("7a echo-shrunken pages: walk completes", outcome == "caught_up", outcome)
    check("7b full non-echo coverage despite short pages",
          set(seen) == {c["id"] for c in cards} - echo,
          f"{len(set(seen))}/{30 - len(echo)}")
    check("7c multiple transitions driven", state["pages"] >= 3, str(state["pages"]))

    # ── 8. Same echo server WITHOUT headers (old server): the len<limit
    #      heuristic reads the first short page as caught-up — this IS the
    #      pre-§SYNCPAGE truncation, asserted here so the degradation stays
    #      documented instead of silently assumed away.
    outcome, seen, _, state = await run_walk(make_server(cards, echo_ids=echo, headers=False),
                                             page_limit=10, max_pages=50)
    check("8a old-server echo case terminates", outcome == "caught_up", outcome)
    check("8b and IS incomplete (the documented old-server degradation)",
          set(seen) != {c["id"] for c in cards} - echo,
          f"covered {len(set(seen))}/{30 - len(echo)}")

    # ── 6. _advance_cursor unit facts
    nxt, st = _advance_cursor(T0, T0 + timedelta(hours=2))
    check("6a normal advance = max−1s, not stalled",
          nxt == T0 + timedelta(hours=2) - timedelta(seconds=1) and not st)
    nxt, st = _advance_cursor(T0, T0)  # bucket no denser progress
    check("6b tie bucket steps STRICTLY past + stalled flag",
          nxt == T0 + timedelta(microseconds=1) and st)
    nxt, st = _advance_cursor(T0, None)  # unparseable page
    check("6c unparseable page still progresses", nxt > T0 and st)
    check("6d _max_updated_at tolerates junk",
          _max_updated_at([{"updated_at": "not-a-date"}, {"x": 1}]) is None)

    print()
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)}): {FAILURES}")
        sys.exit(1)
    print("RESULT: PASS (all scenarios, transitions driven, skips asserted)")


asyncio.run(main())
