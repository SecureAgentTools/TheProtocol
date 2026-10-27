"""§SUITES1018 batch 8 (part 7, 2026-10-19): the admin dispute ruling acts on a dispute the sweep's own agent filed.

Base's seed took the first row of GET /disputes, and an administrator's list holds EVERY dispute (newest first): the
admin ruling row (PUT /admin/disputes/{dispute_id}/ruling, 200 in the V0625 sweep) closes the dispute it names and
moves both parties' reputation. With no seed the fallback was "1", and dispute ids are integers: on sbx-alpha dispute 1
exists (216 disputes, 2026-10-19). Now the seed asks the route's own complainant filter for the sweep's agent, and a
write with none names an id no dispute holds; a read may still name the first.

RED on 1fb9835d (batch 8 part 6b): every test_red_* fails there; the test_control_* one passes on both.
"""
from __future__ import annotations

import asyncio

import httpx

from agentvault_registry.api_tests import base as B

OWN = "did:theprotocol:sweep-agent"


def _run(monkeypatch, method, path, own_disputes):
    seen = []
    real = httpx.AsyncClient

    def _handle(req):
        seen.append((req.method, req.url.path))
        if req.url.path == "/api/v1/disputes":
            if req.url.params.get("complainant_did") == OWN:
                return httpx.Response(200, json=[{"id": d} for d in own_disputes])
            return httpx.Response(200, json=[{"id": 9}, {"id": 1}])     # everyone's, newest first
        return httpx.Response(200, json={"items": []})

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    t = B.APITestBase(base_url="http://registry-test:8000")
    t._dynamic_ids["agent_did"] = OWN
    asyncio.run(t.test_endpoint(method=method, path=path, auth_type="developer", developer_token="admin-token",
                                agent_token="agent-token"))
    return [p for m, p in seen if m == method and p.startswith("/api/v1" + path.split("{", 1)[0])]


def test_red_the_ruling_names_a_dispute_the_sweeps_agent_filed(monkeypatch):
    calls = _run(monkeypatch, "PUT", "/admin/disputes/{dispute_id}/ruling", own_disputes=[42])
    assert calls == ["/api/v1/admin/disputes/42/ruling"], calls


def test_red_with_none_of_its_own_a_write_names_no_dispute(monkeypatch):
    calls = _run(monkeypatch, "PUT", "/admin/disputes/{dispute_id}/ruling", own_disputes=[])
    assert calls == ["/api/v1/admin/disputes/2147483647/ruling"], calls


def test_control_a_read_may_still_name_the_first_dispute(monkeypatch):
    calls = _run(monkeypatch, "GET", "/disputes/{dispute_id}", own_disputes=[])
    assert calls and calls[-1] in ("/api/v1/disputes/1", "/api/v1/disputes/9"), calls
