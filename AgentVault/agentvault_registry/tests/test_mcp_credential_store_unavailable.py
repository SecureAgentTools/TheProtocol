"""§MCPTEST30 (V0529, 2026-10-01) — over MCP, a credential the database could not check is "try again", never
"authentication required", and no MCP answer carries a database driver's words.

agentvault2-21 measured the REST half on sbx-alpha (16:55Z): at the database's connection ceiling a valid admin bearer
answered 401, the console signed out on the 401 and the sign-out revoked the account's tokens everywhere; their fix
(cherry-picked below this commit) answers 503. The MCP bridge had its own two roads to the same mistake: the API key
attempt's catch-all turned a lookup the database could not answer into an ANONYMOUS context (a valid key read "requires
developer authentication", -32001), and a developer JWT's lookup error escaped to the server's last-resort handler,
which answered -32603 "Internal error: <the exception>" with the driver's own sentence in it. Now: MCPAuthUnavailable,
answered -32003 with HTTP 503 and Retry-After by both servers, and one helper (safe_exception_text) withholds a
driver's words from the last-resort text, the background-task text and every tool's exception text.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib

import jwt
import pytest
from sqlalchemy.exc import OperationalError

from agentvault_registry.mcp import auth_bridge as AB
from agentvault_registry.mcp import server as S
from agentvault_registry.mcp import server_admin as SA

CEILING = OperationalError("SELECT developers.id FROM developers WHERE developers.id = $1", {"id_1": 7},
                           Exception("FATAL:  sorry, too many clients already"))


def _run(coro):
    loop = asyncio.new_event_loop()   # never asyncio.run(): it would leave the next test file without a loop
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _raise_ceiling(*_a, **_k):
    raise CEILING


async def _none(*_a, **_k):
    return None


class _CeilingDb:
    """A database at its connection ceiling: every statement is refused."""
    async def execute(self, *_a, **_k):
        raise CEILING


def test_a_developer_jwt_the_database_cannot_check_is_unavailable():
    # V0553: the REAL lookup runs against a database that cannot answer. Until V0553 this patched the bridge's lookup to
    # raise, while the lookup the bridge called (get_developer_by_id) swallowed the error to None: the 503 this asserts
    # never happened, and the token read as a developer that does not exist. The bridge calls the strict lookup now.
    token = jwt.encode({"sub": "7"}, AB.SECRET_KEY, algorithm=AB.ALGORITHM)
    with pytest.raises(AB.MCPAuthUnavailable):
        _run(AB.authenticate_mcp_token(token, db=_CeilingDb()))


def test_an_api_key_the_database_cannot_check_is_unavailable_not_anonymous(monkeypatch):
    monkeypatch.setattr(AB.developer_crud, "get_developer_by_plain_api_key", _raise_ceiling)
    with pytest.raises(AB.MCPAuthUnavailable):
        _run(AB.authenticate_mcp_token("avreg_not-a-real-key", db=None))


def test_control_an_unknown_api_key_is_still_anonymous(monkeypatch):
    monkeypatch.setattr(AB.developer_crud, "get_developer_by_plain_api_key", _none)
    assert _run(AB.authenticate_mcp_token("avreg_not-a-real-key", db=None)).is_anonymous


def test_both_servers_answer_unavailable_503_with_retry_after():
    for err in (S._jsonrpc_error, SA._err):
        r = err(1, -32003, "The registry cannot check credentials right now; try again shortly.")
        assert r.status_code == 503 and r.headers.get("retry-after") == "5"
        r = err(1, -32001, "Authentication required")
        assert r.status_code == 401 and "retry-after" not in r.headers


def test_a_drivers_words_never_leave_through_the_mcp_envelope():
    said = AB.safe_exception_text(CEILING)
    assert said == "the registry's database is busy; try again shortly"
    assert AB.safe_exception_text(ValueError("(sqlalchemy.dialects.postgresql.asyncpg.Error) x\n[SQL: SELECT 1]")) \
        == "a database error occurred"
    assert AB.safe_exception_text(ValueError("plain words")) == "plain words"
    rendered = AB.format_tool_exception(CEILING)
    assert rendered.startswith("OperationalError: ") and "SELECT" not in rendered and "too many" not in rendered


def _tree(mod):
    return ast.parse(pathlib.Path(mod.__file__).with_suffix(".py").read_text(encoding="utf-8"))


def _guarded_calls(tree, callee):
    """Line numbers of `callee(...)` calls that sit inside a try with an `except MCPAuthUnavailable` handler."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Try) and any(h.type is not None and "MCPAuthUnavailable" in ast.unparse(h.type)
                                          for h in n.handlers):
            for c in ast.walk(ast.Module(body=n.body, type_ignores=[])):
                if isinstance(c, ast.Call) and getattr(c.func, "id", "") == callee:
                    out.add(c.lineno)
    return out


def test_every_road_to_the_bridge_is_guarded():
    s, sa = _tree(S), _tree(SA)
    every = lambda t, callee: {c.lineno for c in ast.walk(t) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == callee}
    assert every(s, "_handle_tools_call") and every(s, "_handle_tools_call") <= _guarded_calls(s, "_handle_tools_call")
    assert every(sa, "authenticate_mcp_token") and every(sa, "authenticate_mcp_token") <= _guarded_calls(sa, "authenticate_mcp_token")
    for t in (s, sa):
        text = ast.unparse(t)
        assert 'f"Internal error: {e}"' not in text and "f'Internal error: {e}'" not in text, "the raw last-resort text is back"
