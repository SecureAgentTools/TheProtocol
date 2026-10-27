"""§MCPTEST30 (V0545) — a token check's own refusal is a WARNING, not an "Unexpected error" with a traceback.

verify_agent_token raises its 401 for a token without the agent claims (a developer's token at an agent route) INSIDE
the try whose last handler is `except Exception`, so every such refusal was logged again as "Unexpected error during
agent JWT verification: 401: Could not validate agent credentials" with a stack: 15 in 30 minutes on sbx-alpha from one
tester sweep. verify_temp_password_token had the same shape for a token of another purpose. A real unexpected error
keeps its traceback.
"""
from __future__ import annotations

import asyncio
import logging
import time

import jwt
import pytest
from fastapi import HTTPException

from agentvault_registry import security as sec


def _token(**claims):
    return jwt.encode({"exp": int(time.time()) + 600, **claims}, sec.SECRET_KEY, algorithm=sec.ALGORITHM)


class _Req:
    class state:   # noqa: N801 — a request's state namespace
        pass


def _refused(coro):
    with pytest.raises(HTTPException) as e:
        asyncio.run(coro)
    return e.value


@pytest.mark.parametrize("claims", [
    {"sub": "1", "type": "developer"},                          # a developer's token at an agent route
    {"sub": "did:theprotocol:x", "type": "agent", "agent_id": "not-an-int"},
    {"sub": "did:theprotocol:x", "type": "agent"},              # no agent id
])
def test_an_agent_check_refusal_is_one_warning(caplog, claims):
    caplog.set_level(logging.DEBUG, logger=sec.logger.name)
    err = _refused(sec.verify_agent_token(_Req(), _token(**claims)))
    assert err.status_code == 401 and err.detail == "Could not validate agent credentials"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], [r.getMessage() for r in caplog.records]
    assert [r for r in caplog.records if r.levelno == logging.WARNING and "Agent JWT verification failed" in r.getMessage()]


def test_a_password_set_check_refusal_is_one_warning(caplog):
    caplog.set_level(logging.DEBUG, logger=sec.logger.name)
    err = _refused(sec.verify_temp_password_token(_token(sub="7", purpose="login")))
    assert err.status_code == 401
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_real_unexpected_error_keeps_its_traceback(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger=sec.logger.name)

    def boom(*a, **k):
        raise RuntimeError("the key store is gone")
    monkeypatch.setattr(sec.jwt, "decode", boom)
    err = _refused(sec.verify_agent_token(_Req(), "x.y.z"))
    assert err.status_code == 401
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errs) == 1 and errs[0].exc_info is not None and "Unexpected error" in errs[0].getMessage()


def test_a_good_agent_token_still_passes():
    out = asyncio.run(sec.verify_agent_token(_Req(), _token(sub="did:theprotocol:x", type="agent", agent_id="5")))
    assert out["did"] == "did:theprotocol:x" and out["id"] == 5


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
