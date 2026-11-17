"""D6-495 (V0663, gwo_49ccc7efec6ae43112f5bd72): get_teg_token_for_agent fails loudly when the TEG will not exchange a token.

It used to return an ADMIN_IMPERSONATE marker on any refusal or network error, which prepare_teg_headers turned into the
registry's admin key plus X-Act-As-Agent. No deployed TEG allows impersonation, so the fallback could only fail later with a
401 far from its cause, and it kept the admin key one step from every agent's purse. Now a refusal is a 502 and an unreachable
TEG a 503, said at once; a good exchange still returns the token and caches it.
RED control: against b27f2ebaf the refusal and the network error both RETURN "ADMIN_IMPERSONATE:<did>".
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry.routers import teg_integration as ti

DID = "did:theprotocol:test:agent-1"


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._b, self.text = status, body or {}, str(body or "")

    def json(self):
        return self._b


def _client(answer):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            if isinstance(answer, Exception):
                raise answer
            return answer
    return C


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    import agentvault_registry.security as sec
    monkeypatch.setattr(sec, "create_access_token", lambda *a, **k: "registry-jwt")
    ti._teg_token_cache.clear()
    yield
    ti._teg_token_cache.clear()


def _run(monkeypatch, answer, agent_id=1):
    monkeypatch.setattr(ti.httpx, "AsyncClient", _client(answer))
    return asyncio.run(ti.get_teg_token_for_agent(agent_id, DID))


@pytest.mark.parametrize("status", [401, 404, 500])
def test_a_refused_exchange_is_a_502_not_a_marker(monkeypatch, status):
    with pytest.raises(HTTPException) as e:
        _run(monkeypatch, _Resp(status))
    assert e.value.status_code == 502
    assert str(status) in e.value.detail
    assert "ADMIN_IMPERSONATE" not in e.value.detail


def test_an_unreachable_teg_is_a_503_not_a_marker(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _run(monkeypatch, httpx.ConnectError("down"))
    assert e.value.status_code == 503


def test_a_good_exchange_returns_the_token_and_caches_it(monkeypatch):
    token = _run(monkeypatch, _Resp(200, {"access_token": "teg-jwt", "expires_in": 900}), agent_id=7)
    assert token == "teg-jwt"
    assert 7 in ti._teg_token_cache
    # the second call is the cache's, with no client at all
    monkeypatch.setattr(ti.httpx, "AsyncClient", _client(AssertionError("must not call the TEG")))
    assert asyncio.run(ti.get_teg_token_for_agent(7, DID)) == "teg-jwt"
