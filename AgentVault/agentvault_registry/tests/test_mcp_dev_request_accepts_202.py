"""§MCPTEST30 (2026-09-30) — the developer MCP helper reads 202 Accepted as the success it is.

`POST /api/v1/account/request-deletion` answers 202 with the schedule; `_dev_request` accepted only 200/201 and
returned `{"error": "HTTP 202: ..."}`, which the dispatcher renders "Error: HTTP 202", so requestAccountDeletion told
every MCP caller it had failed while the deletion WAS scheduled. Measured live on sbx-alpha by the self-account
lifecycle (a throwaway account). Controls: 200/201 unchanged, 204 still "deleted", a 4xx still an error.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.mcp import tools_developer as td


class _Resp:
    def __init__(self, code, body):
        self.status_code = code
        self._body = body
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _client_answering(code, body):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, *a, **k):
            return _Resp(code, body)
    return _Client


class _Auth:
    raw_token = "t"


@pytest.fixture(autouse=True)
def _no_auth_check(monkeypatch):
    monkeypatch.setattr(td, "require_developer_auth", lambda auth: None)


@pytest.mark.parametrize("code,body,expect", [
    (202, {"ok": True, "message": "Account scheduled for anonymization"}, {"ok": True, "message": "Account scheduled for anonymization"}),
    (200, {"a": 1}, {"a": 1}),
    (201, {"id": 7}, {"id": 7}),
    (204, None, {"status": "deleted"}),
])
def test_success_statuses_return_the_body(monkeypatch, code, body, expect):
    monkeypatch.setattr(td.httpx, "AsyncClient", _client_answering(code, body))
    assert asyncio.run(td._dev_request(_Auth(), "POST", "/api/v1/account/request-deletion")) == expect


def test_control_a_refusal_is_still_an_error(monkeypatch):
    monkeypatch.setattr(td.httpx, "AsyncClient", _client_answering(400, {"detail": "Confirmation phrase mismatch"}))
    out = asyncio.run(td._dev_request(_Auth(), "POST", "/api/v1/account/request-deletion"))
    assert out == {"error": "HTTP 400: Confirmation phrase mismatch"}
