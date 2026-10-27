"""§WSPOOL (V0637): an authenticated websocket hands its database session back before its receive loop.

A websocket's dependencies live as long as the socket, so the session get_current_user_ws and the endpoint share held a
pooled connection idle in a transaction for a console tab's whole life (sbx-beta, 2026-10-24: 75 s, a console walk's
length, after /ws's organization_members read; idle_in_transaction_session_timeout is 0 there and on EU). Pinned here:
every websocket route that takes the session releases it before it starts receiving (a control: the old shape is
refused), the release closes the session and survives a dead connection, and /ws, driven with fakes, reads the org
memberships, closes the session, and only then waits for a message.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
from types import SimpleNamespace

from starlette.websockets import WebSocketDisconnect

from agentvault_registry.routers import websocket as ws


def _routes_holding_a_session_without_release(module_src: str):
    """Websocket routes that take Depends(get_db) and reach their first receive before _release_ws_session(db)."""
    tree = ast.parse(module_src)
    out = []
    for fn in tree.body:
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        is_ws = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "websocket"
                    for d in fn.decorator_list)
        takes_db = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends"
                       and d.args and isinstance(d.args[0], ast.Name) and d.args[0].id == "get_db"
                       for d in fn.args.defaults + fn.args.kw_defaults if d is not None)
        if not (is_ws and takes_db):
            continue
        releases = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_release_ws_session"]
        receives = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr.startswith("receive")]
        if not releases or (receives and min(releases) > min(receives)):
            out.append(fn.name)
    return out


def test_every_websocket_route_that_takes_the_session_releases_it_before_receiving():
    src = inspect.getsource(ws)
    assert _routes_holding_a_session_without_release(src) == []
    # the four routes this is about are still the ones that take it
    assert src.count("_release_ws_session(db)") == 4


def test_the_check_refuses_the_old_shape():
    old = textwrap.dedent('''
        @router.websocket("/ws")
        async def websocket_endpoint(websocket, current_developer=Depends(get_current_user_ws), db=Depends(get_db)):
            await db.execute("SELECT 1")
            while True:
                data = await websocket.receive_json()
    ''')
    assert _routes_holding_a_session_without_release(old) == ["websocket_endpoint"]


class _Db:
    def __init__(self, log, fail_close=False):
        self.log, self.fail_close = log, fail_close

    async def execute(self, stmt):
        self.log.append("execute")
        return SimpleNamespace(fetchall=lambda: [])

    async def close(self):
        self.log.append("close")
        if self.fail_close:
            raise RuntimeError("connection already closed")


def test_the_release_closes_the_session_and_survives_a_dead_connection():
    log = []
    asyncio.run(ws._release_ws_session(_Db(log)))
    assert log == ["close"]
    log2 = []
    asyncio.run(ws._release_ws_session(_Db(log2, fail_close=True)))   # must not raise
    assert log2 == ["close"]


def test_the_main_socket_reads_closes_and_only_then_receives(monkeypatch):
    log = []

    class _Ws:
        async def receive_json(self):
            log.append("receive")
            raise WebSocketDisconnect(code=1000)

    async def _noop(*a, **k):
        return None

    fake_manager = SimpleNamespace(connect=_noop, broadcast=_noop, send_personal_message=_noop, mark_present=_noop,
                                   subscribe=lambda *a, **k: None, disconnect=lambda *a, **k: None)
    monkeypatch.setattr(ws, "manager", fake_manager)
    monkeypatch.setattr(ws, "_build_user_data", lambda dev, user_id=None: {"id": user_id, "org_ids": []})
    asyncio.run(ws.websocket_endpoint(_Ws(), current_developer=SimpleNamespace(id=7), db=_Db(log)))
    assert log == ["execute", "close", "receive"]
