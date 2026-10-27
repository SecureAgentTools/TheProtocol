"""§FRAMELIC (2026-09-07, findings row 152) — A READ MUST NOT HOLD A WRITE LOCK.

`AgentCRUD.get_or_create` used to end with `db.add(agent); db.flush()` under the note
"Write within current transaction — caller controls commit". **A GET handler is a caller that
never commits.** `GET /api/v1/admin/exchange/escrow` is a read that calls get_or_create for the
shared system account `teg:system:exchange_escrow`, so the first poller to find the row missing
INSERTed it, held the primary-key lock for the life of the request, and every other poller
blocked on `transactionid`.

MEASURED on the EU frame, 2026-09-07:

    state               wait_event_type  wait_event      count  oldest
    idle in transaction Client           ClientRead          1  01:21:00
    active              Lock             transactionid       4  01:21:00

    3147 idle in transaction  SELECT ... WHERE agent_id = 'teg:system:exchange_escrow'
    3230 active  blocked_by {3147}  INSERT INTO agent_teg_profiles ...
    3122 active  blocked_by {3147}  INSERT INTO agent_teg_profiles ...

The whole worker pool was gone for 85 minutes. `/health` timed out, so the container read
`Up (unhealthy)` — and `restart=unless-stopped` does not restart an unhealthy container, only a
crashed one (§CANARYFIX). The registry answered `503 TEG treasury service unavailable`, the
frame's own status page said `EU TEG down`, and the treasury funding of eleven showcase agents
failed eleven times. The docstring had said "In high-concurrency scenarios, consider handling
race conditions" since the MVP; one caller already carries a hand-rolled backoff for the symptom
(`background_tasks/exchange_settlement.py`: "TEG is convoyed — re-hammering the escrow hot row
makes it worse").

A shared system account is the worst case, because every caller races for the SAME row. The fix
is that the create owns its transaction: insert-if-absent on a short-lived session, commit, then
read the row back through the caller's session. The loser of the race sees the winner's row and
nobody holds a lock past their own statement — while the caller's transaction keeps its own
atomicity, because it never wrote this row.
"""
import ast
import pathlib
import sys
from decimal import Decimal

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CRUD = SRC / "teg_core_service" / "database" / "crud.py"


class _Recorder:
    """Counts the transaction verbs. One instance per session so the two are comparable."""

    def __init__(self, name, rows=None):
        self.name = name
        self.calls = []
        self._rows = rows if rows is not None else []

    # caller-session surface
    def query(self, *a, **k):
        self.calls.append("query")
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._rows.pop(0) if self._rows else None

    def add(self, obj):
        self.calls.append("add")

    def flush(self):
        self.calls.append("flush")

    def refresh(self, obj):
        self.calls.append("refresh")

    # independent-session surface
    def execute(self, *a, **k):
        self.calls.append("execute")
        return self

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


def _drive(monkey_rows):
    """Run get_or_create with a missing row; return (caller_calls, own_calls)."""
    from teg_core_service.database import crud as crud_mod
    from teg_core_service.database import db_session as sess_mod

    made = {}

    def _factory():
        made["own"] = _Recorder("own")
        return made["own"]

    real = sess_mod.SessionLocal
    sess_mod.SessionLocal = _factory
    try:
        caller = _Recorder("caller", rows=list(monkey_rows))
        crud_mod.AgentCRUD.get_or_create(caller, "teg:system:exchange_escrow")
        return caller.calls, made.get("own", _Recorder("none")).calls
    finally:
        sess_mod.SessionLocal = real


def test_the_create_commits_on_its_own_session():
    """The row is committed immediately, so no lock outlives the statement."""
    _caller, own = _drive([None, object()])   # miss, then the winner's row on re-read
    assert "execute" in own and "commit" in own, own
    assert "close" in own, f"the independent session must be closed: {own}"


def test_the_callers_transaction_never_writes_the_row():
    """CONTROL — the caller must not `add`/`flush` it, or the convoy is back."""
    caller, _own = _drive([None, object()])
    assert "add" not in caller, f"caller session wrote the row: {caller}"
    assert "flush" not in caller, f"caller session flushed the row: {caller}"


def test_a_present_row_is_returned_without_any_write():
    """CONTROL — the common path (row exists) must not touch a second session at all."""
    from teg_core_service.database import db_session as sess_mod

    sentinel = object()
    calls = []
    real = sess_mod.SessionLocal
    sess_mod.SessionLocal = lambda: calls.append("opened")
    try:
        from teg_core_service.database.crud import AgentCRUD
        caller = _Recorder("caller", rows=[sentinel])
        got = AgentCRUD.get_or_create(caller, "teg:system:exchange_escrow")
        assert got is sentinel
        assert calls == [], f"a hit must not open a second session: {calls}"
        assert "add" not in caller.calls and "flush" not in caller.calls
    finally:
        sess_mod.SessionLocal = real


def test_source_no_longer_claims_the_caller_commits():
    """The note that licensed the bug must be gone, and the finding named."""
    src = CRUD.read_text()
    assert "caller controls commit" not in src, (
        "the comment that licensed a read path to hold a write lock is back")
    assert "row 152" in src, "the finding that earned this must be named at the fix"
