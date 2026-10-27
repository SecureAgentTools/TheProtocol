"""§FRAMELIC (2026-09-07, findings row 165) — THE BACKSTOP FOR `agents.liquid_balance`.

Row 164 fixed the event-driven writer of this cache. This is the worker that notices when that
writer is wrong AGAIN, because the column had no backstop at all: `balance_reconciliation_guard`
sounds like one and reconciles a DIFFERENT projection (the EventStore's `materialized_balances`),
so nothing watched the number every console, agent list and admin view actually reads. That is how
a 250-unit bond, a cross-frame debit and a cross-frame credit all sat wrong for an hour with
Δ=0.0 and every health signal green.

The tests pin the four decisions that make it a backstop rather than a second writer:

  * it heals through `_sync_agent_from_teg` — the SAME function the reactor calls, so exactly one
    piece of code decides what this cache contains (the batch's own lesson: four defects in one
    night were one fact computed in two places);
  * a heal is a WARNING, not an INFO — the real-time path was supposed to have done it, and the
    alarm is the point. The healing is cheap;
  * an agent that keeps needing healing is ESCALATED by DID, because a backstop that silently
    fixes the same row every sweep is hiding a broken reactor rather than reporting one;
  * the slice cursor WRAPS, because there is no batch balance rail (even
    `POST /developers/me/agents/balances` fans out one TEG call per agent), so a busy frame is
    covered over time instead of in a burst.
"""
import asyncio
import contextlib
import pathlib
import sys
from decimal import Decimal

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

MOD = SRC / "agentvault_registry" / "background_tasks" / "liquid_balance_reconciler.py"
MAIN = SRC / "agentvault_registry" / "main.py"


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """Answers the two selects the cycle makes, in order: the slice, then the re-read."""

    def __init__(self, script):
        self._script = list(script)

    async def execute(self, *_a, **_k):
        return _Result(self._script.pop(0) if self._script else [])


def _install(monkey, rows_before, rows_after, sync_spy=None):
    """Point the module at a fake DB and a spied sync helper; return the worker."""
    from agentvault_registry.background_tasks import liquid_balance_reconciler as m

    script = [rows_before, rows_after]

    @contextlib.asynccontextmanager
    async def _ctx():
        yield _FakeDB([script.pop(0)] if script else [[]])

    monkey.append((m, "get_db_context", m.get_db_context))
    m.get_db_context = _ctx

    async def _spy(did):
        if sync_spy is not None:
            sync_spy.append(did)

    monkey.append((m, "_sync_agent_from_teg", m._sync_agent_from_teg))
    m._sync_agent_from_teg = _spy
    return m


def _restore(monkey):
    for mod, name, orig in monkey:
        setattr(mod, name, orig)


def test_it_heals_through_the_one_writer_and_never_updates_the_column_itself():
    monkey, asked = [], []
    m = _install(monkey, rows_before=[(1, "did:theprotocol:eu.x:aaa", Decimal("1000"))],
                 rows_after=[("did:theprotocol:eu.x:aaa", Decimal("750"))], sync_spy=asked)
    try:
        w = m.LiquidBalanceReconciler()
        _run(w._cycle_once())
        assert asked == ["did:theprotocol:eu.x:aaa"], asked
        assert w._stats["healed"] == 1, w._stats
    finally:
        _restore(monkey)
    # and structurally: it must not write the column itself
    src = MOD.read_text()
    assert "liquid_balance =" not in src, "the reconciler must not become a second writer"
    assert "_sync_agent_from_teg" in src


def test_a_matching_cache_is_not_reported_as_a_heal():
    """CONTROL — the quiet case must be quiet, or the alarm means nothing."""
    monkey, asked = [], []
    m = _install(monkey, rows_before=[(1, "did:theprotocol:eu.x:aaa", Decimal("750"))],
                 rows_after=[("did:theprotocol:eu.x:aaa", Decimal("750"))], sync_spy=asked)
    try:
        w = m.LiquidBalanceReconciler()
        _run(w._cycle_once())
        assert w._stats["healed"] == 0, w._stats
        assert w._stats["checked"] == 1, w._stats
    finally:
        _restore(monkey)


def test_system_accounts_are_not_checked():
    monkey, asked = [], []
    m = _install(monkey, rows_before=[(1, "did:theprotocol:teg_system_treasury", Decimal("1"))],
                 rows_after=[], sync_spy=asked)
    try:
        w = m.LiquidBalanceReconciler()
        _run(w._cycle_once())
        assert asked == [], asked
        assert w._stats["checked"] == 0, w._stats
    finally:
        _restore(monkey)


def test_repeated_healing_of_one_agent_is_escalated_by_did():
    """A backstop that keeps fixing the same row is hiding a broken reactor."""
    from agentvault_registry.background_tasks import liquid_balance_reconciler as m

    monkey = []
    try:
        w = None
        for i in range(m.MAX_HEALS_PER_AGENT + 1):
            local, asked = [], []
            mm = _install(local, rows_before=[(1, "did:theprotocol:eu.x:aaa", Decimal(1000 + i))],
                          rows_after=[("did:theprotocol:eu.x:aaa", Decimal("750"))], sync_spy=asked)
            if w is None:
                w = mm.LiquidBalanceReconciler()
            try:
                w._cursor_id = 0
                _run(w._cycle_once())
            finally:
                _restore(local)
        assert "did:theprotocol:eu.x:aaa" in w._escalated, w._heal_count
    finally:
        _restore(monkey)


def test_the_cursor_wraps_so_a_big_frame_is_covered():
    """With no batch rail, a slice per cycle is the only affordable sweep — it must not stick."""
    monkey, asked = [], []
    m = _install(monkey, rows_before=[], rows_after=[], sync_spy=asked)
    try:
        w = m.LiquidBalanceReconciler()
        w._cursor_id = 99999
        _run(w._cycle_once())
        assert w._cursor_id == 0, "an exhausted slice must reset the cursor, not stall at the end"
    finally:
        _restore(monkey)


def test_a_heal_is_a_warning_not_an_info():
    """Keyed on the MESSAGE, not on `if healed:` — there are two of those (one guards the
    metrics increment), and splitting on the first picked the wrong branch. A structural test
    that matches the wrong region passes or fails for reasons unrelated to what it claims."""
    import ast

    tree = ast.parse(MOD.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and "corrected" in str(first.value):
            assert node.func.attr == "warning", (
                f"a heal is logged at {node.func.attr} — the real-time path failed and that "
                f"must not read as routine")
            return
    raise AssertionError("no log call reporting a correction was found")


def test_it_is_started_and_stopped():
    src = MAIN.read_text()
    assert "start_liquid_balance_reconciler()" in src, "a worker nobody starts does not exist"
    assert "await stop_liquid_balance_reconciler()" in src, "and it must be stopped cleanly"


def test_it_can_be_switched_off_without_a_code_change():
    src = MOD.read_text()
    assert "LIQUID_BALANCE_RECONCILE_ENABLED" in src
    assert '"true"' in src.split("_should_run")[1][:300], "default ON — a backstop nobody enables is not one"
