"""§MCPTEST30 (V0641, agentvault2-66 2026-10-25): the buy door's two wording defects from agentvault2-5b's console run
fes-20261025T100811Z-8ef9 on sbx-alpha (a member's buy of the WeatherAgent; the card's address answered 404).

- The receipt read "Paid 0.500000 SBXA · nothing charged": on a call that fails at transport, /buy releases the
  reservation but kept paid_amount, which authorize had set. No settle runs on that path, so nothing was paid, whatever
  the release answers; a release that lands also says "You were not charged." like the not-delivered path does.
- The error read "{'detail': 'Not Found', 'type': 'not_found'}": call_agent read the 404 page's `error` object as a
  JSON-RPC error and str()'d it. An error is said in words (a JSON-RPC message, an HTTP body's detail or title), with
  the HTTP status when it is no JSON-RPC answer; never the repr of a dict.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agentvault_registry.routers import a2a_payment as ap
from agentvault_registry.services import service_purchase as sp

_DID = "did:theprotocol:sandbox-a.theprotocol.cloud:d506dd2e-ea2c-4908-9833-3e368f30abb5"
_NOT_FOUND = {"error": {"detail": "Not Found", "type": "not_found"}}


def _run(c):
    return asyncio.run(c)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class _Client:
    def __init__(self, release_status):
        self.release_status, self.posts = release_status, []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append(url)
        if url.endswith("/a2a-payment/authorize"):
            return _Resp(200, {"token": "apt_x", "token_id": "00e13d76-23d2-4f8d-9393-cb44758485f0",
                               "amount": "0.500000", "currency": "SBXA"})
        if "/a2a-payment/release-by-id/" in url:
            return _Resp(self.release_status, {"detail": "ok" if self.release_status == 200 else "consumed"})
        raise AssertionError(f"unexpected call {url}")


@pytest.fixture
def buy(monkeypatch):
    def _go(release_status):
        async def _quote(db, request, did):
            return ap.QuoteResponse(target_agent_did=did, payment_required=True, price="0.5",
                                    price_currency="SBXA", recommended_amount="0.500000", can_buy=True,
                                    endpoint="https://sandbox-a.theprotocol.cloud/weather-agent/a2a")

        async def _call(client, endpoint, payload, token, issuer):
            return {"ok": False, "http_status": 404, "body": _NOT_FOUND, "error": "HTTP 404: Not Found"}

        client = _Client(release_status)
        monkeypatch.setattr(ap, "_quote_for", _quote)
        monkeypatch.setattr(ap, "_get_settle_client", lambda: client)
        monkeypatch.setattr(sp, "call_agent", _call)
        req = ap.BuyRequest(target_agent_did=_DID, text="Berlin")
        request = SimpleNamespace(headers={"Authorization": "Bearer tok"})
        return _run(ap.buy_service(req, request, None, None)), client
    return _go


def test_a_released_buy_reports_no_payment_and_says_nothing_was_charged(buy):
    resp, client = buy(200)
    assert resp.stage == "failed" and resp.settlement_status == "released"
    assert resp.paid_amount is None and resp.paid_currency is None, "an authorization is not a payment"
    assert resp.error == "HTTP 404: Not Found You were not charged."
    assert any("/release-by-id/" in u for u in client.posts)


def test_a_refused_release_reports_no_payment_either(buy):
    resp, _client = buy(400)
    assert resp.settlement_status == "release_refused"
    assert resp.paid_amount is None and resp.paid_currency is None, "no settle ran: nothing was paid"
    assert "You were not charged." not in resp.error, "the reservation was not handed back: nothing claims it was"


def _call_with(status, body=None, text=None):
    def handler(request):
        if text is not None:
            return httpx.Response(status, text=text, headers={"Content-Type": "text/html"})
        return httpx.Response(status, json=body)

    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sp.call_agent(c, "https://agent.example.test/a2a", {"jsonrpc": "2.0"}, "apt_x", None)
    return _run(_go())


@pytest.fixture(autouse=True)
def _no_ssrf_lookup(monkeypatch):
    monkeypatch.setattr(sp, "assert_callable_endpoint", lambda u: u)


@pytest.mark.parametrize("status,body,text,want", [
    (404, _NOT_FOUND, None, "HTTP 404: Not Found"),                      # the card's address, 2026-10-25
    (404, {"detail": "Not Found"}, None, "HTTP 404: Not Found"),
    (402, {"jsonrpc": "2.0", "error": {"code": -32099, "message": "Payment Required — include X-Payment-Token header"},
           "id": None}, None, "Payment Required — include X-Payment-Token header"),   # the agent's own answer
    (200, {"jsonrpc": "2.0", "error": {"code": -32000, "message": "city not found"}, "id": 1}, None, "city not found"),
    (200, {"jsonrpc": "2.0", "error": {"code": -32000}, "id": 1}, None, '{"code": -32000}'),
    (502, None, "<html><body>Bad Gateway</body></html>", "HTTP 502"),     # an error page is not an answer to quote
    (500, {"error": "boom"}, None, "HTTP 500: boom"),
])
def test_an_error_is_said_in_words(status, body, text, want):
    out = _call_with(status, body, text)
    assert out["ok"] is False
    assert out["error"] == want
    assert "{'" not in out["error"], "never the repr of a dict"


def test_a_delivered_answer_has_no_error():
    out = _call_with(200, {"jsonrpc": "2.0", "result": {"state": "COMPLETED"}, "id": 1})
    assert out["ok"] is True and out["error"] == ""


@pytest.mark.parametrize("e,want", [
    ({"message": "m", "detail": "d"}, "m"),
    ({"detail": {"message": "nested"}}, "nested"),
    ({"title": "Forbidden"}, "Forbidden"),
    ({}, ""),
    ("plain", "plain"),
    (None, ""),
])
def test_error_words(e, want):
    assert sp.error_words(e) == want
