"""§MCPTEST30 (2026-10-01) — the ledger agreement probe: over the lifecycle phase, the change in the sentinel's TEG
balance and the change in its EventStore projection must agree.

A dropped emit is invisible to the supply delta (CLAUDE.md PART 4); only a comparison of the two ledgers sees it. The
verdict works on CHANGES, so drift an agent carried before the run never reads as a finding; the store is written a
moment after the TEG, so the after-read waits for it before calling a gap a finding.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from decimal import Decimal

from agentvault_registry.api_tests.contracts import ledger_agreement as LA


def snap(teg_l, teg_s, st_l, st_s, events):
    return {"teg": {"liquid": Decimal(teg_l), "staked": Decimal(teg_s)},
            "store": {"liquid": Decimal(st_l), "staked": Decimal(st_s), "events": events}}


T0 = snap("100", "10", "90", "10", 500)   # the store already 10 behind on liquid: drift from before the run


def test_agreeing_changes_pass_whatever_the_drift_before():
    healthy, sentence, ev = LA.verdict(T0, snap("93.5", "12", "83.5", "12", 507))
    assert healthy is True and sentence is None
    assert ev["teg_liquid"] == "-6.5" and ev["store_events_added"] == 7


def test_a_move_the_store_never_heard_of_is_the_finding():
    healthy, sentence, _ev = LA.verdict(T0, snap("93.5", "10", "90", "10", 500))
    assert healthy is False and sentence.startswith("BUG-FIND: ledger") and "liquid: TEG -6.5 vs store +0" in sentence


def test_a_float_projection_within_a_micro_unit_agrees():
    assert LA.verdict(T0, snap("93.5", "10", "83.5000000004", "10", 503))[0] is True


def test_nothing_moved_is_not_measured():
    healthy, sentence, _ev = LA.verdict(T0, snap("100", "10", "90", "10", 500))
    assert healthy is None and sentence.startswith("NOT MEASURED")


def _close(t0, reads):
    out, slept = {}, []
    seq = iter(reads)

    async def fake_snapshot(rpc, parse, bag):
        return next(seq, None)

    async def fake_sleep(s):
        slept.append(s)

    def make_outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"healthy": ok, "fail_reason": fail, "skip_reason": skip_reason}

    real = LA.snapshot
    LA.snapshot = fake_snapshot
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(LA.close(None, None, None, t0, out, make_outcome, sleep=fake_sleep))
    finally:
        loop.close()
        LA.snapshot = real
    return out[LA.ROW], slept


def test_the_after_read_waits_for_a_lagging_store():
    lagging = snap("93.5", "10", "90", "10", 500)        # the TEG moved, the store not yet
    caught_up = snap("93.5", "10", "83.5", "10", 503)
    row, slept = _close(T0, [lagging, None, caught_up])
    assert row["healthy"] is True and slept == [0, 3, 5]


def test_a_gap_that_never_closes_is_reported_after_every_wait():
    row, slept = _close(T0, [snap("93.5", "10", "90", "10", 500)] * 5)
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND") and slept == list(LA.WAITS)


def test_no_before_snapshot_is_not_measured():
    row, _ = _close(None, [])
    assert row["skip_reason"].startswith("NOT MEASURED")


def test_the_flow_reads_before_the_lifecycle_sweep_and_after_the_token_heal():
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    src = pathlib.Path(F.__file__).with_suffix(".py").read_text(encoding="utf-8")
    snap_at = src.index("_ledger0 = await _ledger.settled_snapshot(")   # V0545: the before-read waits for the store
    sweep_at = src.index("LIFECYCLES, _run_one_lifecycle,")
    heal_at = src.index("possibly-dead credential; expect a 401 cascade.")
    close_at = src.index("await _ledger.close(")
    assert snap_at < sweep_at < heal_at < close_at
    assert '"ledger: "' in src
    ast.parse(src)


def _settle(reads):
    """settled_snapshot over a fixed sequence of reads, with the sleeps recorded."""
    seq, slept = iter(reads), []

    async def fake_snapshot(rpc, parse, bag):
        return next(seq, None)

    async def fake_sleep(s):
        slept.append(s)
    real = LA.snapshot
    LA.snapshot = fake_snapshot
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(LA.settled_snapshot(None, None, None, sleep=fake_sleep)), slept
    finally:
        loop.close()
        LA.snapshot = real


# Round 13 (run 6aa4b0ed5e9a42df): the setup phase's last guild escrows (-1.0 each) were on the TEG and not yet in the
# store when the before-read ran; the journals matched one for one. Balances relative to the sentinel's 5000 grant.
R13_LAGGING = snap("4646.0", "100", "4650.0", "100", 13)      # the TEG has four -1.0 the store has not heard of yet
R13_CAUGHT = snap("4646.0", "100", "4646.0", "100", 17)
R13_AFTER = snap("4604.792976", "110", "4604.792976", "110", 37)


def test_the_before_read_waits_until_the_store_catches_up():
    s, slept = _settle([R13_LAGGING, R13_CAUGHT, R13_CAUGHT])
    assert s["settled"] is True and s["store"]["events"] == 17 and slept == [2]


# V0585: the 03:00Z run of 2026-10-08 (sbx-alpha, V0584). The store held still for a read or two while four guild escrows
# (-1.0 each) waited in the TEG's outbox (emitted 3-8 s after the change); two equal reads settled V0545's before-read.
R08_LAGGING = snap("3746.0", "0", "3750.0", "0", 3)
R08_CAUGHT = snap("3746.0", "0", "3746.0", "0", 7)
R08_AFTER = snap("3719.792477", "0", "3719.792477", "0", 28)


def test_a_store_that_holds_still_while_it_lags_is_not_settled():
    s, slept = _settle([R08_LAGGING, R08_LAGGING, R08_LAGGING, R08_CAUGHT])
    assert s["settled"] is True and s["store"]["events"] == 7 and slept == [2, 3, 4]
    healthy, sentence, _ev = LA.verdict(R08_LAGGING, R08_AFTER)          # what V0584 compared against
    assert healthy is False and "liquid: TEG -26.207523 vs store -30.207523" in sentence
    assert LA.verdict(s, R08_AFTER)[0] is True


def test_a_drifted_ledger_settles_only_after_holding_still_past_the_emit_lag():
    drifted = snap("100", "10", "90", "10", 500)            # the store 10 behind from before the run: never caught up
    s, slept = _settle([drifted] * 6)
    assert s["settled"] is True and slept == [2, 3, 4, 6] and sum(slept[1:]) >= LA.STILL_SPAN
    moving = [snap("100", "10", "90", "10", 500 + n) for n in range(6)]     # drifted AND still receiving
    s, slept = _settle(moving)
    assert s["settled"] is False and slept == list(LA.SETTLE_WAITS)


def test_round_13_reads_red_on_a_one_shot_before_and_agrees_on_a_settled_one():
    healthy, sentence, _ev = LA.verdict(R13_LAGGING, R13_AFTER)   # what V0543 did: one read, mid-flight
    assert healthy is False and "liquid: TEG -41.207024 vs store -45.207024" in sentence
    settled, _ = _settle([R13_LAGGING, R13_CAUGHT, R13_CAUGHT])
    assert LA.verdict(settled, R13_AFTER)[0] is True


def test_a_before_read_that_never_settles_makes_a_gap_not_measured():
    moving = [snap("200", "0", str(100 + n), "0", n) for n in range(10, 20)]   # behind, and the store keeps receiving
    s, slept = _settle(moving)
    assert s["settled"] is False and slept == list(LA.SETTLE_WAITS)
    teg, store, events = s["teg"]["liquid"], s["store"]["liquid"], s["store"]["events"]
    healthy, sentence, ev = LA.verdict(s, snap(str(teg - 10), "0", str(store - 5), "0", events + 3))
    assert healthy is None and sentence.startswith("NOT MEASURED: the ledgers were still moving") and ev["before_settled"] is False
    assert LA.verdict(s, snap(str(teg - 10), "0", str(store - 10), "0", events + 3))[0] is True, "agreement is still a pass"


def test_a_caught_up_first_read_settles_at_once():
    s, slept = _settle([R13_CAUGHT])
    assert s["settled"] is True and slept == []


def test_an_unreadable_ledger_during_the_settle_is_none():
    assert _settle([R13_LAGGING, None])[0] is None
    assert _settle([None])[0] is None
