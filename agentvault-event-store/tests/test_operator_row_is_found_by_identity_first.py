"""§TRUSTROW (2026-09-16, his word "1. approved"): a peer's row is found by the identity it votes with, then by licence.

The vote weight resolves a voter by its SPIFFE id (services/federation_governance.py:70-90, whose caller passes
`auth_context.get("spiffe_id") or operator_id or "origin"`), while the registry's trust sync keyed its refresh by the
LICENCE id. A SPIFFE URI never equals a UUID, so the two never met: measured on the live stores 2026-09-16, EU held two
rows for the same peer frame (the licence-keyed one carrying the measured 0.974, the spiffe-keyed one the vote reads
stuck at 1), and ASIA held no row at its licence id at all, so its sync answered 400 every cycle against the insert
branch, which requires a hash the sync never sends.

`find_operator_row` is that lookup, in one place: the identity first, the licence id second.

  1. a row carrying the payload's spiffe_id is returned, and the licence-id query is never run;
  2. with no spiffe match, the licence id still finds the row (an operator, or a frame before it has an identity);
  3. a payload with no spiffe_id asks only by licence id, exactly as before;
  4. nothing matches: None, so the caller's insert branch (which still demands license_key_hash) decides;
  5. (structure) the sync handler calls this helper and no longer selects the operator itself, and its insert branch
     still refuses without a hash.

RED before the change: find_operator_row does not exist and the handler selects by id inline.
Run: python -m pytest tests/test_operator_row_is_found_by_identity_first.py -q
"""
import ast
import asyncio
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENTS = ROOT / "src" / "routers" / "events.py"


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    """Answers by what the compiled statement asks for, and remembers the order it was asked."""

    def __init__(self, by_spiffe=None, by_id=None):
        self.by_spiffe, self.by_id, self.asked = by_spiffe, by_id, []

    async def execute(self, stmt):
        # The WHERE clause decides, not the column list: every SELECT here names spiffe_id among its columns, so a
        # naive `"spiffe_id" in sql` answers the identity row to both queries and the fallback can never be seen.
        # `Select.whereclause` renders empty under this SQLAlchemy, so read the text after WHERE.
        sql = " ".join(str(stmt).split())  # the rendering puts WHERE on its own line, so normalise first
        where = sql.split(" WHERE ", 1)[1] if " WHERE " in sql else ""
        if "spiffe_id" in where:
            self.asked.append("spiffe")
            return _Result(self.by_spiffe)
        self.asked.append("id")
        return _Result(self.by_id)


def _find():
    from src.routers import events
    fn = getattr(events, "find_operator_row", None)
    assert callable(fn), "src/routers/events.py has no find_operator_row: the lookup is still inline and licence-first"
    return fn


def test_red_a_row_with_the_payload_identity_wins_and_the_licence_query_never_runs():
    db = _Db(by_spiffe="the spiffe row", by_id="the licence row")
    got = asyncio.run(_find()(db, "11111111-1111-1111-1111-111111111111", "spiffe://asia.theprotocol.cloud"))
    assert got == "the spiffe row"
    assert db.asked == ["spiffe"], db.asked


def test_the_licence_id_still_finds_a_row_when_no_identity_matches():
    db = _Db(by_spiffe=None, by_id="the licence row")
    got = asyncio.run(_find()(db, "11111111-1111-1111-1111-111111111111", "spiffe://asia.theprotocol.cloud"))
    assert got == "the licence row"
    assert db.asked == ["spiffe", "id"], db.asked


def test_a_payload_without_an_identity_asks_only_by_licence_id():
    db = _Db(by_spiffe="never reached", by_id="the licence row")
    got = asyncio.run(_find()(db, "11111111-1111-1111-1111-111111111111", None))
    assert got == "the licence row"
    assert db.asked == ["id"], db.asked


def test_nothing_matches_is_none_so_the_insert_branch_decides():
    db = _Db(by_spiffe=None, by_id=None)
    assert asyncio.run(_find()(db, "11111111-1111-1111-1111-111111111111", "spiffe://x")) is None
    assert db.asked == ["spiffe", "id"], db.asked


def test_red_the_handler_uses_the_helper_and_keeps_its_insert_rule():
    tree = ast.parse(EVENTS.read_text())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and any("license_key_hash is required when creating a new federation operator" in ast.dump(x)
                       for x in ast.walk(n))), None)
    assert fn is not None, "the sync handler is not where this test expects it"
    calls = [ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)]
    assert "find_operator_row" in calls, "the handler does not go through the one lookup"
    selects = [ast.unparse(c) for c in ast.walk(fn) if isinstance(c, ast.Call) and ast.unparse(c.func) == "select"]
    assert not any("FederationOperator" in s for s in selects), f"the handler still selects the operator itself: {selects}"
    assert "license_key_hash is required" in EVENTS.read_text(), "the insert branch stopped requiring a hash"
