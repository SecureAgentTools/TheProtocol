"""§DOCSFIX D6-261 (2026-10-16): GET /api/v1/teg/balance answers plain digits, never exponent form.

`_normalize_balance` strips the TEG's 18 trailing decimal places with `Decimal.normalize()`, which writes a whole number
that ends in zeros in exponent form: a new agent's balance after its genesis grant of 1000 read "1E+3" (and 250 read
"2.5E+2"), which `int()` refuses and a reader takes for a different number. The route now answers "1000".
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.routers import teg_integration as T
from agentvault_registry.security import get_current_agent


class _R:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def _client(monkeypatch, teg_balance):
    class _TegClient:
        async def get(self, *a, **k):
            return _R(200, {"agent_id": "did:theprotocol:probe", "balance": teg_balance})

    async def _token(agent_id, agent_did):
        return "teg-token"

    monkeypatch.setattr(T, "_get_teg_client", lambda: _TegClient())
    monkeypatch.setattr(T, "get_teg_token_for_agent", _token)
    app = FastAPI()
    app.include_router(T.router, prefix="/api/v1")
    app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(id=7, did="did:theprotocol:probe")
    return TestClient(app)


@pytest.mark.parametrize("teg_balance,want", [
    ("1000.000000000000000000", "1000"),
    ("250.000000000000000000", "250"),
    ("990.000000000000000000", "990"),
    ("19942.000000000000000000", "19942"),
    ("100.500000000000000000", "100.5"),
    ("0.000000000000000001", "0.000000000000000001"),
    ("0E-18", "0"),
])
def test_the_balance_route_answers_plain_digits(monkeypatch, teg_balance, want):
    r = _client(monkeypatch, teg_balance).get("/api/v1/teg/balance")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance"] == want
    assert "E" not in body["balance"].upper()


def test_a_whole_balance_reads_back_as_an_integer(monkeypatch):
    r = _client(monkeypatch, "1000.000000000000000000").get("/api/v1/teg/balance")
    assert int(r.json()["balance"]) == 1000
