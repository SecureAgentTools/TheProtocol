"""D6-298 (2026-10-16): the store's lockdown reaches every worker and survives a restart.

The lockdown lived in the memory of the one worker that took POST /api/v1/system/lockdown: on a store running several
workers (the frame kit runs `uvicorn --workers N`) the others went on appending, a restart lifted it, and with
EVENTSTORE_HTTP_VIA_KAFKA the append route published to the broker without asking at all. It now lives in the store's
database (one row, src/services/lockdown_state.py); each worker reads it at most once per LOCKDOWN_CACHE_SECONDS.

Pure tests load lockdown_state.py alone (no FastAPI, no database) and give two LockdownState instances, two workers,
one shared row (a stand-in for the table); the SQL itself runs against Postgres in tests/test_lockdown_table.py.
Wiring tests read the source: every append path awaits the shared answer before it writes or publishes, none reads
a worker's own flag in its place, the system routes go through the shared row, and startup creates the table.

Run: python -m pytest tests/test_lockdown_shared.py -q   (needs pytest only)
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not (ROOT / "src").is_dir():
    ROOT = pathlib.Path("/app")
SRC = ROOT / "src"


def _lockdown_module():
    """services/lockdown_state.py on its own (the services package imports the database)."""
    spec = importlib.util.spec_from_file_location("lockdown_state_under_test", SRC / "services" / "lockdown_state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SharedRow:
    """The one lockdown row, as every worker of a store sees it in the database."""

    def __init__(self):
        self.row = None
        self.reads = 0
        self.fail = False
        self.delay = 0.0

    async def read(self):
        self.reads += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("the store's database is unreachable")
        return dict(self.row) if self.row else None

    async def activate(self, reason, triggered_by):
        if self.row and self.row["is_active"]:
            return False, dict(self.row)
        self.row = {"is_active": True, "reason": reason, "triggered_by": triggered_by,
                    "triggered_at": datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc)}
        return True, dict(self.row)

    async def clear(self):
        before = dict(self.row) if self.row else None
        if self.row:
            self.row = {"is_active": False, "reason": None, "triggered_at": None, "triggered_by": "system"}
        return before


def _workers(n=2, cache_seconds=0):
    mod, row = _lockdown_module(), SharedRow()
    return row, [mod.LockdownState(store=row, cache_seconds=cache_seconds) for _ in range(n)]


def test_a_lockdown_taken_by_one_worker_stops_the_others():
    row, (a, b) = _workers()

    async def go():
        assert await b.is_locked() is False
        assert await a.activate("supply breach: delta 5", "supply_auditor") is True
        assert await b.is_locked() is True
        assert (b.reason, b.triggered_by, b.triggered_at) == ("supply breach: delta 5", "supply_auditor",
                                                              "2026-10-16T21:00:00+00:00")
        assert "supply breach: delta 5" in b.detail()
        assert (await a.clear()) == (True, "supply breach: delta 5")
        assert await b.is_locked() is False
        assert b.to_dict() == {"lockdown_active": False, "reason": None, "triggered_at": None, "triggered_by": "system"}
    asyncio.run(go())


def test_a_restarted_worker_is_still_locked():
    row, (a,) = _workers(1)
    mod = _lockdown_module()

    async def go():
        await a.activate("supply breach", "supply_auditor")
        restarted = mod.LockdownState(store=row, cache_seconds=0)      # a new process: nothing in its memory
        assert restarted.is_active is False
        assert await restarted.is_locked() is True
    asyncio.run(go())


def test_the_first_lockdown_stays_when_another_worker_activates():
    row, (a, b) = _workers()

    async def go():
        assert await a.activate("first", "supply_auditor") is True
        assert await b.activate("second", "admin") is False
        assert (b.reason, b.triggered_by) == ("first", "supply_auditor")
        assert row.row["reason"] == "first"
    asyncio.run(go())


def test_an_append_costs_no_query_within_the_interval():
    row, (a, b) = _workers(cache_seconds=60)

    async def go():
        for _ in range(100):
            assert await b.is_locked() is False
        assert row.reads == 1
        await a.activate("supply breach", "supply_auditor")
        assert await a.is_locked() is True and row.reads == 1     # the activating worker knows at once
        b._read_at -= 61                                          # the interval passes for the other worker
        assert await b.is_locked() is True and row.reads == 2
    asyncio.run(go())


def test_appends_arriving_while_the_row_is_read_wait_for_it():
    """Measured end to end (3 workers, 45 concurrent appends after the interval): 11 got 201 after the lockdown while
    one read was in flight and the others answered from the old copy. The burst must wait for that one read."""
    row, (a, b) = _workers(cache_seconds=60)

    async def go():
        assert await b.is_locked() is False
        await a.activate("supply breach", "supply_auditor")
        row.delay = 0.05
        b._read_at -= 61
        answers = await asyncio.gather(*(b.is_locked() for _ in range(20)))
        assert answers == [True] * 20
        assert row.reads == 2, "one read for the whole burst"
    asyncio.run(go())


def test_a_failed_read_keeps_the_last_answer():
    row, (a, b) = _workers()

    async def go():
        await a.activate("supply breach", "supply_auditor")
        assert await b.is_locked() is True
        row.fail = True
        assert await b.is_locked() is True          # an error never unlocks
        fresh = _lockdown_module().LockdownState(store=row, cache_seconds=0)
        assert await fresh.is_locked() is False     # and never locks: no answer yet, so the copy (unlocked) stands
        row.fail = False
        assert await fresh.is_locked() is True
    asyncio.run(go())


def test_no_row_means_never_locked():
    row, (a,) = _workers(1)

    async def go():
        assert await a.is_locked() is False
        assert (await a.clear()) == (False, None)
    asyncio.run(go())


# ── wiring: read from the source ─────────────────────────────────────────────────────────────────────────────────────

def _function(path: pathlib.Path, name: str, cls: str = None) -> ast.AST:
    tree = ast.parse(path.read_text())
    scope = tree.body
    if cls:
        scope = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls).body
    return next(n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _awaited_check_lines(fn: ast.AST) -> list:
    return [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Await) and "GLOBAL_LOCKDOWN.is_locked()" in ast.unparse(n)]


def _first_line(fn: ast.AST, needle: str) -> int:
    lines = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and needle in ast.unparse(n.func)]
    assert lines, f"{getattr(fn, 'name', fn)}: no call to {needle}"
    return min(lines)


def test_every_append_path_awaits_the_shared_answer_before_it_writes():
    cases = [
        (_function(SRC / "services" / "event_store.py", "append_event", cls="EventStore"), "self.db.add"),
        (_function(SRC / "services" / "kafka_consumer.py", "_process_batch"), "AsyncSessionLocal"),
        (_function(SRC / "services" / "kafka_consumer.py", "_process_message"), "AsyncSessionLocal"),
        (_function(SRC / "routers" / "events.py", "append_event"), "publisher.publish"),
    ]
    for fn, write in cases:
        checks = _awaited_check_lines(fn)
        assert checks, f"{fn.name}: no awaited GLOBAL_LOCKDOWN.is_locked()"
        assert min(checks) < _first_line(fn, write), f"{fn.name}: the lockdown check must come before {write}"


def test_no_append_path_gates_on_a_workers_own_flag():
    for path, name, cls in ((SRC / "services" / "event_store.py", "append_event", "EventStore"),
                            (SRC / "services" / "kafka_consumer.py", "_process_batch", None),
                            (SRC / "services" / "kafka_consumer.py", "_process_message", None),
                            (SRC / "routers" / "events.py", "append_event", None)):
        fn = _function(path, name, cls)
        gates = [ast.unparse(n.test) for n in ast.walk(fn) if isinstance(n, ast.If) and "GLOBAL_LOCKDOWN" in ast.unparse(n.test)]
        assert gates and all("is_locked()" in g for g in gates), f"{name}: gates {gates}"


def test_the_system_routes_go_through_the_shared_row():
    system = SRC / "routers" / "system.py"
    expected = {"activate_lockdown": "await GLOBAL_LOCKDOWN.activate(", "clear_lockdown": "await GLOBAL_LOCKDOWN.clear()",
                "get_lockdown_status": "await GLOBAL_LOCKDOWN.is_locked()"}
    for name, call in expected.items():
        assert call in ast.unparse(_function(system, name)), f"{name} does not {call}"


def test_startup_creates_the_table_under_the_migration_lock():
    startup = ast.unparse(_function(SRC / "main.py", "startup_event"))
    assert "_LOCKDOWN_TABLE_DDL" in startup and "lockdown_state import TABLE_DDL" in startup
    assert startup.index("pg_try_advisory_xact_lock") < startup.index("_LOCKDOWN_TABLE_DDL"), \
        "the table is created by the worker that holds the migration lock"
