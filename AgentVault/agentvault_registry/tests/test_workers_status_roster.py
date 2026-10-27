"""§VITALS S3 (batch 2, 2026-09-05) — /admin/workers/status lists the DECLARED roster, not a hand-kept dict."""
import os
import pathlib
import re

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

from agentvault_registry.routers.admin_health import merge_worker_roster, _schedule_label  # noqa: E402


def test_roster_decides_the_rows_and_descriptions_only_decorate():
    roster = [
        {"worker_id": "velocity_snapshot", "module": "background_tasks.velocity_snapshot", "pattern": "loop", "interval_sec": 300, "enabled": True},
        {"worker_id": "brand_new_worker", "module": "background_tasks.brand_new", "pattern": "subscriber", "interval_sec": None, "enabled": False},
    ]
    desc = {"velocity_snapshot": {"desc": "Velocity metrics", "sched": "5min", "cat": "ledger"},
            "ghost_of_2026_05": {"desc": "a worker the dict remembers and nothing runs", "sched": "60s", "cat": "x"}}
    rows = merge_worker_roster(roster, desc)
    names = [r["name"] for r in rows]
    assert names == ["brand_new_worker", "velocity_snapshot"], names
    new = rows[0]
    assert new["description"].startswith("background_tasks.brand_new") and new["category"] == "undescribed" and new["enabled"] is False
    assert new["schedule_label"] == "?"
    vs = rows[1]
    assert vs["description"] == "Velocity metrics" and vs["category"] == "ledger" and vs["schedule_label"] == "5min"
    assert "ghost_of_2026_05" not in names, "a description cannot resurrect a worker that never registered"


def test_schedule_label_from_declared_interval():
    assert _schedule_label(5) == "5s" and _schedule_label(300) == "5min" and _schedule_label(21600) == "6hr" and _schedule_label(None) == "?"


def test_the_route_no_longer_iterates_the_hand_kept_dict():
    src = (pathlib.Path(__file__).resolve().parent.parent / "src/agentvault_registry/routers/admin_health.py").read_text()
    assert "for task_name, meta in KNOWN_TASKS.items()" not in src
    assert "merge_worker_roster(snap.get(\"workers\")" in src
    assert "add to KNOWN_TASKS" not in src, "the old undocumented-worker sentence is gone"


# ── §FRAMELIC (2026-09-07, findings row 166) ────────────────────────────────────────────────
# `/admin/workers/status` reported `last_run_at: null` for EVERY BackgroundWorker — 20 of them on
# the EU/ASIA frames, the supply auditor among them — so the one field an operator uses to ask
# "is this thing still running?" was blank for the entire modern worker population.
#
# Two halves that never met. The rail read a legacy flat Redis key (`worker:<name>:last_run_at`)
# written only by `leader.run_with_leadership`; `BackgroundWorker._run_loop` does not use that
# pattern — it acquires leadership directly and records the cycle with `vitals.stamp()`. The
# freshness existed the whole time, in the snapshot the rail was ALREADY fetching, and
# `merge_worker_roster` dropped `w["state"]` one line before building the row that reports it.
#
# This is §VITALS' own warning turned on the instrument: a status rail that cannot distinguish
# "never ran" from "I am not reading where it writes" is worse than no rail, because the blank
# reads as death. The writer's own comment said the rail was "kept until S3 moves that rail onto
# the vitals roster" — the move simply never happened.

def test_last_run_at_comes_from_the_state_the_worker_actually_writes():
    roster = [{
        "worker_id": "liquid_balance_reconciler",
        "module": "background_tasks.liquid_balance_reconciler",
        "pattern": "BackgroundWorker", "interval_sec": 300, "enabled": True,
        "state": {
            "last_cycle_at": "2026-09-07T14:51:30+00:00",
            "last_success_at": "2026-09-07T14:51:30+00:00",
            "last_outcome": "ok",
            "last_error": "",
        },
    }]
    row = merge_worker_roster(roster, {})[0]
    assert row["last_run_at"] == "2026-09-07T14:51:30+00:00", row
    assert row["last_success_at"] == "2026-09-07T14:51:30+00:00", row
    assert row["last_outcome"] == "ok", row


def test_a_turn_is_not_a_success_and_the_row_says_both():
    """§VITALS: a worker can turn faithfully while every cycle fails. The row must let an
    operator see that — a `last_run_at` that moves while `last_success_at` does not is the
    whole point of keeping two clocks."""
    roster = [{
        "worker_id": "some_worker", "module": "m", "pattern": "BackgroundWorker",
        "interval_sec": 60, "enabled": True,
        "state": {
            "last_cycle_at": "2026-09-07T15:00:00+00:00",
            "last_success_at": "2026-09-07T09:00:00+00:00",
            "last_outcome": "error",
            "last_error": "TEG unreachable",
        },
    }]
    row = merge_worker_roster(roster, {})[0]
    assert row["last_run_at"] != row["last_success_at"]
    assert row["last_outcome"] == "error"
    assert row["last_error"] == "TEG unreachable"


def test_no_state_leaves_the_fields_empty_so_the_legacy_fallback_can_fire():
    """CONTROL — a worker that registered but has not stamped must NOT get a fabricated
    timestamp; the route falls back to the legacy flat key only when this is None."""
    roster = [{"worker_id": "never_stamped", "module": "m", "pattern": "loop",
               "interval_sec": 60, "enabled": True}]
    row = merge_worker_roster(roster, {})[0]
    assert row["last_run_at"] is None, row
    assert row["last_success_at"] is None, row


def test_the_route_prefers_vitals_and_only_then_the_legacy_key():
    """Order matters: the legacy key is written by ONE pattern, vitals by both."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "routers" / "admin_health.py").read_text()
    block = src.split('last_run = {"last_run_at": row.get("last_run_at")')[1][:400]
    assert 'if not last_run["last_run_at"]:' in block, block
    assert "_last_run_meta(task_name)" in block, block


def test_the_descriptions_are_still_only_decoration():
    """CONTROL — the original contract of this function must not have shifted."""
    rows = merge_worker_roster(
        [{"worker_id": "w1", "module": "m", "pattern": "p", "interval_sec": 60, "enabled": True}],
        {"ghost": {"desc": "nothing runs this", "sched": "1h", "cat": "x"}},
    )
    assert [r["name"] for r in rows] == ["w1"]


def test_an_idle_subscriber_is_distinguishable_from_a_dead_one():
    """§FRAMELIC row 166, the half that is easy to get wrong.

    ~50 of the rows in this rail are REACTORS. A reactor that has not fired has done no work,
    so `last_run_at` is correctly null — but it is not dead, and a rail where "idle" and "dead"
    look identical is the blank-reads-as-death problem again, one layer down. `last_turn_at` is
    stamped inside `try_acquire_leadership`, so any leader-elected worker has one whether or not
    it had anything to do.

    Stamping the heartbeat as if it were WORK would be the wrong fix: it would make a dead
    handler indistinguishable from a busy one, which is §VITALS' "a turn is not a success" in
    reverse. Hence three clocks, not one.
    """
    roster = [{
        "worker_id": "reactor_admin_broadcast_sent", "module": "m", "pattern": "auto(leader)",
        "interval_sec": None, "enabled": True,
        "state": {"last_turn_at": "2026-09-07T15:20:00+00:00"},   # alive, nothing to do
    }]
    row = merge_worker_roster(roster, {})[0]
    assert row["last_run_at"] is None, "an idle subscriber has done no work — do not fake it"
    assert row["last_turn_at"] == "2026-09-07T15:20:00+00:00", row


def test_a_reactor_stamps_its_dispatches_so_last_run_at_can_ever_be_set():
    """The rail can only show what the worker writes; reactors wrote nothing."""
    import ast

    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "background_tasks" / "reactor_base.py").read_text()
    tree = ast.parse(src)
    stamped = {"ok": False, "error": False}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "stamp"):
            continue
        for a in node.args:
            if isinstance(a, ast.Attribute) and a.attr == "OUTCOME_OK":
                stamped["ok"] = True
            if isinstance(a, ast.Attribute) and a.attr == "OUTCOME_ERROR":
                stamped["error"] = True
    assert stamped["ok"], "a successful dispatch must move last_run_at AND last_success_at"
    assert stamped["error"], (
        "a failing dispatch must move last_run_at but NOT last_success_at — separate clocks")


def test_reactor_instrumentation_can_never_break_a_handler():
    """CONTROL — a stamp is instrumentation. If Redis is down, the handler still runs."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "background_tasks" / "reactor_base.py").read_text()
    chunks = src.split("_v.stamp(")[1:]
    # Pair the loop with the COUNT it assumes: with no stamp calls this test passed vacuously
    # on the unfixed file — `all()` over an empty list is True, which is the exact trap the
    # doctrine warns about and which I walked into writing this control.
    assert len(chunks) >= 2, f"expected the success and error stamps, found {len(chunks)}"
    for chunk in chunks:
        window = chunk[:400]
        assert "except Exception" in window, (
            "every stamp call must sit inside a try/except — instrumentation must not be able "
            "to take down the thing it measures")


# ── §FRAMELIC (2026-09-07, findings row 167) ────────────────────────────────────────────────
# "Four workers that never turned" was three correct behaviours and one lie. `canary_judge` and
# `canary_rebalancer` were DISABLED (`CANARY_*_ENABLED=false`), `staking_distributor` was WARMING
# (a daily job at boot) — and `fiat_routed_local_reconciler` registered `enabled=True` and THEN
# returned on its own gate, so it read WARMING for a worker that had already decided never to run.
# WARMING expires into NEVER_RAN and then reads as a fault.
#
# The deeper problem: `/admin/workers/status` — the rail an operator actually opens — showed three
# raw timestamps and no interpretation, while the verdict logic existed in a DIFFERENT rail. A
# blank `last_run_at` means five things (off · not due · nothing to do · dead · never started).

def test_a_disabled_worker_is_disabled_not_never_ran():
    from agentvault_registry.routers.admin_health import worker_verdict
    assert worker_verdict({"worker_id": "canary_judge", "enabled": False,
                           "interval_sec": 5, "registered_at": "2020-01-01T00:00:00+00:00"}) == "DISABLED"


def test_a_daily_worker_at_boot_is_warming_not_a_fault():
    from datetime import datetime, timezone, timedelta
    from agentvault_registry.routers.admin_health import worker_verdict
    now = datetime.now(timezone.utc)
    w = {"worker_id": "staking_distributor", "enabled": True, "interval_sec": 86400,
         "registered_at": (now - timedelta(minutes=5)).isoformat()}
    assert worker_verdict(w, now) == "WARMING"


def test_past_its_first_interval_with_nothing_recorded_IS_a_fault():
    """CONTROL — WARMING must expire, or the verdict can never report a dead worker."""
    from datetime import datetime, timezone, timedelta
    from agentvault_registry.routers.admin_health import worker_verdict
    now = datetime.now(timezone.utc)
    w = {"worker_id": "w", "enabled": True, "interval_sec": 300,
         "registered_at": (now - timedelta(hours=2)).isoformat()}
    assert worker_verdict(w, now) == "NEVER_RAN"


def test_a_failing_cycle_reads_erroring_even_though_it_ran():
    from datetime import datetime, timezone
    from agentvault_registry.routers.admin_health import worker_verdict
    now = datetime.now(timezone.utc)
    w = {"worker_id": "w", "enabled": True, "interval_sec": 300,
         "registered_at": now.isoformat(),
         "state": {"last_cycle_at": now.isoformat(), "last_outcome": "error"}}
    assert worker_verdict(w, now) == "ERRORING"


def test_the_status_rail_carries_the_verdict_and_the_gate():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    rows = merge_worker_roster([{
        "worker_id": "fiat_routed_local_reconciler", "module": "m", "pattern": "hand-rolled",
        "interval_sec": 3600, "enabled": False, "gate": "ROUTED_FIAT_ENABLED=false",
        "registered_at": now.isoformat(),
    }], {})
    assert rows[0]["verdict"] == "DISABLED", rows[0]
    assert rows[0]["gate"] == "ROUTED_FIAT_ENABLED=false", (
        "a DISABLED row should say off BECAUSE OF WHAT — `gate` was a roster field nothing filled")


def test_the_two_rails_share_one_definition():
    """Two rails answering the same question with two implementations is how they drift —
    the defect this batch met three times (rows 154, 157, 166)."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "routers" / "admin_health.py").read_text()
    assert src.count("def worker_verdict(") == 1, "exactly one definition"
    assert src.count('verdict = "DISABLED"') == 0, (
        "the vitals rail must call the shared function, not keep its own copy")
    assert src.count("worker_verdict(") >= 3, "defined once, used by both rails"


def test_the_reconciler_declares_its_gate_before_obeying_it():
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "background_tasks" / "fiat_routed_local_reconciler.py").read_text()
    reg = src.split("_vitals.register(")[1][:400]
    assert "enabled=True" not in reg, (
        "it registered enabled=True and then returned on its own gate — WARMING for a worker "
        "that will never run")
    assert "gate=" in reg, "and it should name which flag stopped it"
