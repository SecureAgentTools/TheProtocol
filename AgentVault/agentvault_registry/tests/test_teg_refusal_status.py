"""§MCPTEST30 (V0524, 2026-10-01) — a TEG refusal reaches the caller as the refusal it is, not as an outage.

Every TEG proxy route in routers/teg_integration.py ended in an `else` that called any other TEG answer "Unable to ...
at this time", 503: a TEG 422 for a value it validates, a 409, a 400 from its nginx all read as "the TEG is down, try
again". The MCP tester's hostile-input probe met it as 503s from eight read routes (sbx-alpha, V0515), and on a write
(a system transfer, a policy, a dispute, an attestation) it told a caller to retry a refusal. `_teg_refusal` passes a
TEG 4xx through with its status and reason; a 401/403 (the registry's own credential to the TEG), a 429 and a 5xx
stay 503 with the route's sentence.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import teg_integration as T


class _R:
    def __init__(self, status, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.mark.parametrize("status,body,text,want_status,want_detail", [
    (422, {"detail": "agent_id: at most 128 characters"}, None, 422, "The TEG refused the request (HTTP 422): agent_id: at most 128 characters"),
    (409, {"detail": {"code": "exists"}}, None, 409, 'The TEG refused the request (HTTP 409): {"code": "exists"}'),
    (400, None, "<html><body>400 Bad Request</body></html>", 400, "The TEG refused the request (HTTP 400)"),
    (404, {"detail": "Policy not found"}, None, 404, "The TEG refused the request (HTTP 404): Policy not found"),
    (401, {"detail": "bad key"}, None, 503, "Unable to fetch policy at this time"),
    (403, {"detail": "forbidden"}, None, 503, "Unable to fetch policy at this time"),
    (429, {"detail": "slow down"}, None, 503, "Unable to fetch policy at this time"),
    (500, {"detail": "boom"}, None, 503, "Unable to fetch policy at this time"),
    (502, None, "<html>bad gateway</html>", 503, "Unable to fetch policy at this time"),
])
def test_a_teg_answer_maps_to_what_it_means(status, body, text, want_status, want_detail):
    e = T._teg_refusal(_R(status, body, text), "Unable to fetch policy at this time")
    assert isinstance(e, HTTPException)
    assert (e.status_code, e.detail) == (want_status, want_detail)


def test_every_fall_through_goes_through_the_helper():
    src = pathlib.Path(T.__file__).read_text()
    left = re.findall(r'status_code=status\.HTTP_503_SERVICE_UNAVAILABLE,\n\s+detail="Unable to [^"\n]* at this time"', src)
    assert left == [], left
    assert src.count("raise _teg_refusal(response, ") == 18


def test_a_route_passes_the_tegs_refusal_through(monkeypatch):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _R(422, {"detail": "policy_id is not a UUID"})

    monkeypatch.setattr(T.httpx, "AsyncClient", _C)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(T.get_teg_policy("mcp-probe", current_developer=object()))
    assert ei.value.status_code == 422
    assert ei.value.detail == "The TEG refused the request (HTTP 422): policy_id is not a UUID"
