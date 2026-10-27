"""§RELEASEHARDEN D2 (2026-09-14) — the websocket JWT rides the subprotocol list, never the query string.

Driven through Starlette's test client against a small app that mounts the real `get_current_user_ws`
dependency with the database replaced: the subprotocol token authenticates and the server selects
`theprotocol.v1` (a browser closes the socket itself when it offered subprotocols and the server picked
none); since V0377 the query form is refused with 1008 (§MTLSHOPS (d)), counted and warned; without any
token the close is 1008 too. The pure helpers are pinned
on their own so the parsing rule (comma-separated, trimmed, prefix-matched) is a fact and not a hope.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient
import jwt
from starlette.websockets import WebSocketDisconnect

from agentvault_registry.database import get_db
from agentvault_registry.routers import websocket as wsmod


class _Dev:
    id = 7
    email = "seven@example.test"


class _Result:
    def scalar_one_or_none(self):
        return _Dev()


class _FakeDB:
    async def execute(self, *_a, **_k):
        return _Result()


async def _fake_db():
    yield _FakeDB()


def _app() -> FastAPI:
    app = FastAPI()

    @app.websocket("/ws")
    async def endpoint(websocket: WebSocket, dev=Depends(wsmod.get_current_user_ws)):
        await websocket.accept(subprotocol=wsmod._select_subprotocol(websocket))
        await websocket.send_text(f"dev:{dev.id}")
        await websocket.close()

    app.dependency_overrides[get_db] = _fake_db
    return app


def _token() -> str:
    return jwt.encode({"sub": "7"}, wsmod.SECRET_KEY, algorithm=wsmod.ALGORITHM)


class _FakeWS:
    def __init__(self, header: str | None):
        self.headers = {} if header is None else {"sec-websocket-protocol": header}


def test_helpers_parse_the_offered_list():
    ws = _FakeWS("theprotocol.v1, theprotocol.bearer.eyJ.a.b")
    assert wsmod._offered_subprotocols(ws) == ["theprotocol.v1", "theprotocol.bearer.eyJ.a.b"]
    assert wsmod._token_from_subprotocol(ws) == "eyJ.a.b"
    assert wsmod._select_subprotocol(ws) == "theprotocol.v1"


def test_helpers_without_an_offer_answer_none():
    ws = _FakeWS(None)
    assert wsmod._offered_subprotocols(ws) == []
    assert wsmod._token_from_subprotocol(ws) is None
    assert wsmod._select_subprotocol(ws) is None
    assert wsmod._token_from_subprotocol(_FakeWS("theprotocol.bearer.")) is None, "an empty bearer is no token"
    assert wsmod._select_subprotocol(_FakeWS("other.proto")) is None, "an unknown offer selects nothing"


def test_subprotocol_token_authenticates_and_the_server_selects_v1():
    client = TestClient(_app())
    with client.websocket_connect("/ws", subprotocols=["theprotocol.v1", wsmod.WS_BEARER_PREFIX + _token()]) as ws:
        assert ws.accepted_subprotocol == "theprotocol.v1"
        assert ws.receive_text() == "dev:7"


def test_subprotocol_token_wins_over_a_query_token(caplog):
    client = TestClient(_app())
    with caplog.at_level(logging.WARNING, logger=wsmod.logger.name):
        with client.websocket_connect("/ws?token=not-a-jwt", subprotocols=["theprotocol.v1", wsmod.WS_BEARER_PREFIX + _token()]) as ws:
            assert ws.receive_text() == "dev:7"
    assert not any("query-string token" in r.getMessage() for r in caplog.records)


def test_query_token_is_refused_counted_and_warned(caplog):
    client = TestClient(_app())
    with caplog.at_level(logging.WARNING, logger=wsmod.logger.name):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws?token={_token()}") as ws:
                ws.receive_text()
    assert exc.value.code == 1008
    assert exc.value.reason == "query_token_not_accepted"
    assert any("refused a query-string token" in r.getMessage() for r in caplog.records)


def test_the_fallback_switch_is_gone():
    # §MTLSHOPS (d): removed at V0377 once its counter read zero; no environment turns the query form back on
    assert not hasattr(wsmod, "WS_QUERY_TOKEN_ALLOWED")


def test_no_token_at_all_is_1008_and_still_selects_the_offered_subprotocol():
    client = TestClient(_app())
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", subprotocols=["theprotocol.v1"]) as ws:
            assert ws.accepted_subprotocol == "theprotocol.v1"
            ws.receive_text()
    assert exc.value.code == 1008
    assert exc.value.reason == "unauthorized"


def test_a_bad_subprotocol_token_is_1008_invalid_token():
    client = TestClient(_app())
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", subprotocols=["theprotocol.v1", wsmod.WS_BEARER_PREFIX + "eyJ.not.valid"]) as ws:
            ws.receive_text()
    assert exc.value.code == 1008
    assert exc.value.reason == "invalid_token"


def test_docker_stats_route_authenticates_through_the_dependency():
    # the old body called get_current_user_ws(token) with the token in the websocket position
    import inspect

    params = inspect.signature(wsmod.websocket_docker_stats).parameters
    deps = [getattr(p.default, "dependency", None) for p in params.values()]
    assert wsmod.get_current_user_ws in deps
    assert "token" not in params
