"""§MCPTEST30 (V0553): the per-request developer lookups read the developer's own row, never every card and key it owns.

The auth path eager-loaded every agent card (card_data included) and every API key of the developer on each request, so
a request cost grew with the account: the sandbox frames' admin owns 6,712 cards and 533 keys, and its /developers/me
took 0.6-1.8 s against 12 ms for an anonymous read (sbx-alpha and sbx-beta, 2026-10-02); an MCP call paid it twice.
Pinned by compiling the statements (a fixture of three cards passes with or without the loads): the two auth lookups
carry no loader option, the general lookup still does (the control), and the four request paths call the lean ones.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest
from sqlalchemy.exc import SQLAlchemyError

from agentvault_registry.crud import developer as D

SRC = pathlib.Path(D.__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class _Db:
    def __init__(self, fail: bool = False):
        self.stmts, self.fail = [], fail

    async def execute(self, stmt):
        self.stmts.append(stmt)
        if self.fail:
            raise SQLAlchemyError("connection refused")

        class _Result:
            def scalar_one_or_none(self):
                return None
        return _Result()


def _options(lookup) -> tuple:
    db = _Db()
    asyncio.run(lookup(db, 7))
    (stmt,) = db.stmts
    return tuple(stmt._with_options)


def test_the_auth_lookups_load_no_relationship_and_the_general_one_still_does():
    assert _options(D.get_developer_by_id_strict) == ()
    assert _options(D.get_developer_by_id_lean) == ()
    assert len(_options(D.get_developer_by_id)) == 2, "the control: the reader must see the general lookup's two loads"


def test_each_keeps_its_error_contract():
    with pytest.raises(SQLAlchemyError):          # the required path maps it to a 503, never a 401
        asyncio.run(D.get_developer_by_id_strict(_Db(fail=True), 7))
    assert asyncio.run(D.get_developer_by_id_lean(_Db(fail=True), 7)) is None


def _crud_calls(path: pathlib.Path, function: str) -> set:
    tree = ast.parse(path.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
    return {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and getattr(n.func.value, "id", "") == "developer_crud"}


@pytest.mark.parametrize("path,function,lookup", [
    ("security.py", "get_current_developer", "get_developer_by_id_strict"),
    ("security.py", "get_current_developer_optional", "get_developer_by_id_lean"),
    ("security.py", "get_current_developer_unified", "get_developer_by_id_lean"),
    ("mcp/auth_bridge.py", "_authenticate_mcp_token", "get_developer_by_id_strict"),
])
def test_the_request_paths_use_the_lean_lookups(path, function, lookup):
    calls = _crud_calls(SRC / path, function)
    assert lookup in calls, (function, calls)
    assert "get_developer_by_id" not in calls, f"{function} loads every card and key the developer owns again"
