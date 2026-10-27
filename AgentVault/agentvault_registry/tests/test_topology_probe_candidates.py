"""§MCPTEST30 (V0636): the admin topology probe tries every candidate until one reads ok.

A frame's base_url is its federation address (:8443), whose /health answers 400 to a caller without a client
certificate. The probe returned the first answer, so every frame and operator peer read ok=false (sbx-alpha's three
active peers, each on :8443, measured by the MCP tester's earned federation lifecycle), and the console host without
the port was never asked.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from agentvault_registry.routers import federation_topology as ft


class _Result:
    def __init__(self, peer):
        self._peer = peer

    def scalar_one_or_none(self):
        return self._peer


class _Db:
    def __init__(self, peer):
        self.peer = peer

    async def execute(self, _stmt):
        return _Result(self.peer)


def _run(base_url, handler, monkeypatch):
    real = httpx.AsyncClient

    def _client(*a, **k):
        k.pop("verify", None)
        return real(transport=httpx.MockTransport(handler), **k)
    monkeypatch.setattr(ft.httpx, "AsyncClient", _client)
    peer = SimpleNamespace(id=7, base_url=base_url)
    return asyncio.run(ft.peer_probe(peer_id=7, db=_Db(peer)))


def test_a_federation_port_that_wants_a_certificate_falls_through_to_the_console_host(monkeypatch):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.port == 8443:
            return httpx.Response(400, text="No required SSL certificate was sent")
        return httpx.Response(200, text="ok")
    out = _run("https://frame.example.test:8443", handler, monkeypatch)
    assert out["ok"] is True and out["url"] == "https://frame.example.test/health"
    assert seen[:2] == ["https://frame.example.test:8443/health", "https://frame.example.test/health"]


def test_with_no_candidate_ok_the_first_answer_stands_and_says_what_was_tried(monkeypatch):
    out = _run("https://frame.example.test:8443", lambda req: httpx.Response(503, text="down"), monkeypatch)
    assert out["ok"] is False and out["status_code"] == 503 and out["url"].endswith(":8443/health")
    assert len(out["tried"]) == 3


def test_an_unreachable_peer_still_says_so(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("no route", request=req)
    out = _run("https://nowhere.example.test", handler, monkeypatch)
    assert out == {"ok": False, "error": "All probe endpoints unreachable",
                   "tried": ["https://nowhere.example.test/health", "https://nowhere.example.test"]}
