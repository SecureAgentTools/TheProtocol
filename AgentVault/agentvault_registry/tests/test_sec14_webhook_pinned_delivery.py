"""SEC-14 (2026-10-17): a webhook delivery connects to an address it checked, never to one the HTTP client looks up again.

D6-760 made every delivery resolve the stored URL at the moment of sending and refuse it when any address is internal.
The send then handed the URL to httpx, which resolved the name a second time: a name whose answer changes between the
two lookups (a short TTL, a rebinding resolver) passed the check with a public address and was delivered to an internal
one. Now the delivery connects to one of the addresses the check approved; the request still names the webhook's host
(its Host header and, for https, the TLS server name, so the certificate is verified for that name) and asks for the
connection to be closed after the answer. When connecting to an address fails, the next checked address is tried.

Through FastAPI on the real router (POST /api/v1/webhooks/{id}/test) and on the retry path. The resolver is a table
whose answer can change between lookups; the HTTP client's transport connects like a real one would: a request
addressed to a NAME is resolved again (the next answer) and reaches what that answer says, one addressed to an address
reaches that address. RED on 453cc8b8 (its webhook_service and input_validators mounted): both rebinding cases reach
127.0.0.1, the request carries no TLS server name and no closed connection, and the fallback never runs.
"""
import datetime as dt
import ipaddress
import socket
import types

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import webhooks
from agentvault_registry.services.webhook_service import WebhookService

EVENT = WebhookService.SUPPORTED_EVENTS[0]
# public addresses the export allows anywhere (its G13 refuses any other public IPv4 in a shipped file)
PUBLIC, PUBLIC_2, PUBLIC_V6 = "93.184.216.34", "1.2.3.4", "2606:2800:220:1:248:1893:25c8:1946"


class _Dns:
    """socket.getaddrinfo from a table; a name's answers are taken in turn, the last one kept (a rebinding resolver)."""

    def __init__(self):
        self.answers, self.asked = {}, []

    def __call__(self, host, port, *a, **k):
        self.asked.append(host)
        seq = self.answers.get(host)
        if not seq:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        addrs = seq.pop(0) if len(seq) > 1 else seq[0]
        return [((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, port, 0, 0)) if ":" in a
                 else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))) for a in addrs]


@pytest.fixture
def dns(monkeypatch):
    d = _Dns()
    monkeypatch.setattr(socket, "getaddrinfo", d)
    return d


@pytest.fixture
def wire(monkeypatch, dns):
    """Every request the delivery makes, and the address it reached."""
    seen, refuse = [], set()

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        try:
            ipaddress.ip_address(host)
            reached = host
        except ValueError:   # a name: the client resolves it again before it connects
            reached = dns(host, request.url.port or 443)[0][4][0]
        if reached in refuse:
            raise httpx.ConnectError("connection refused", request=request)
        seen.append({"url": str(request.url), "reached": reached, "host": request.headers.get("host"),
                     "sni": request.extensions.get("sni_hostname"), "connection": request.headers.get("connection"),
                     "signature": request.headers.get("x-theprotocol-signature")})
        return httpx.Response(200, text="ok")

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return types.SimpleNamespace(seen=seen, refuse=refuse)


def _hook(url):
    return types.SimpleNamespace(id="wh-1", developer_id=7, url=url, events=[EVENT], secret="s" * 32, is_active=True,
                                 failure_count=0, created_at=dt.datetime.now(dt.timezone.utc), updated_at=None,
                                 last_triggered_at=None, description=None)


class _Db:
    def __init__(self, hook):
        self.hook, self.added = hook, []

    async def execute(self, stmt, params=None):
        hook = self.hook
        return types.SimpleNamespace(scalar_one_or_none=lambda: hook)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


def _test_route(hook):
    app = FastAPI()
    app.include_router(webhooks.router)
    dev = types.SimpleNamespace(id=7, email="dev@example.test", is_admin=False)
    app.dependency_overrides[webhooks.get_current_developer] = lambda: dev
    app.dependency_overrides[security.get_current_developer] = lambda: dev
    db = _Db(hook)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    return TestClient(app).post("/api/v1/webhooks/wh-1/test"), db


def test_a_delivery_goes_to_the_address_its_check_approved_not_to_a_second_lookup(dns, wire):
    dns.answers["rebind.example"] = [[PUBLIC], ["127.0.0.1"]]   # public when checked, internal when asked again
    r, db = _test_route(_hook("https://rebind.example/h?x=1"))
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    (sent,) = wire.seen
    assert sent["reached"] == PUBLIC, f"the delivery reached {sent['reached']}, an address nobody checked"
    assert sent["url"] == f"https://{PUBLIC}/h?x=1"
    assert (sent["host"], sent["sni"], sent["connection"]) == ("rebind.example", "rebind.example", "close")
    assert sent["signature"], "the signed request is unchanged"
    assert dns.asked == ["rebind.example"], "one lookup: the one that was checked"
    assert db.added and db.added[0].response_status == 200


def test_a_retry_goes_to_the_address_its_check_approved(dns, wire):
    dns.answers["rebind.example"] = [[PUBLIC], ["10.9.8.7"]]
    svc = WebhookService()
    hook = _hook("http://rebind.example:8080/hook")
    delivery = types.SimpleNamespace(id="d-1", event_type=EVENT, retry_count=0, delivered_at=None,
                                     payload={"id": "d-1", "event": EVENT, "data": {}, "timestamp": None,
                                              "agent_did": None},
                                     response_status=None, response_body=None, error_message=None, next_retry_at=None)
    import asyncio
    asyncio.run(svc.retry_delivery(delivery, hook, _Db(hook)))
    (sent,) = wire.seen
    assert sent["reached"] == PUBLIC and sent["url"] == f"http://{PUBLIC}:8080/hook"
    assert (sent["host"], sent["sni"]) == ("rebind.example:8080", None), "plain http carries no TLS server name"
    assert delivery.response_status == 200


def test_when_an_address_refuses_the_connection_the_next_checked_one_is_tried(dns, wire):
    dns.answers["two.example"] = [[PUBLIC, PUBLIC_V6], ["127.0.0.1"]]
    wire.refuse.add(PUBLIC)
    r, _ = _test_route(_hook("https://two.example/h"))
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    (sent,) = wire.seen
    assert sent["reached"] == PUBLIC_V6 and sent["url"] == f"https://[{PUBLIC_V6}]/h"
    assert sent["sni"] == "two.example" and dns.asked == ["two.example"]


def test_a_name_with_any_internal_address_is_still_refused_and_nothing_is_sent(dns, wire):
    dns.answers["mixed.example"] = [[PUBLIC_2, "192.168.1.9"]]
    r, db = _test_route(_hook("https://mixed.example/h"))
    assert r.status_code == 200 and not r.json()["success"]
    assert wire.seen == [] and "refused" in (db.added[0].error_message or "")


def test_a_host_that_resolves_to_nothing_is_a_failed_send_not_a_send_to_a_second_lookup(dns, wire):
    r, db = _test_route(_hook("https://later.invalid/h"))
    assert not r.json()["success"] and wire.seen == []
    assert "resolves to no address" in (db.added[0].error_message or "")
    assert db.added[0].next_retry_at is not None, "it is retried like any failed send"


def test_control_an_address_literal_is_sent_as_written(dns, wire):
    r, _ = _test_route(_hook(f"https://{PUBLIC_2}/h"))
    assert r.json()["success"] is True and dns.asked == []
    (sent,) = wire.seen
    assert sent["url"] == f"https://{PUBLIC_2}/h" and sent["host"] == PUBLIC_2
