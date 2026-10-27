"""D6-760 (2026-10-16): a webhook URL may not reach an internal address, by any route, at any moment.

Three holes, one class. The older pair POST/PUT /api/v1/developers/webhooks stored any URL unchecked (a literal
127.0.0.1, any scheme). The canonical validator (input_validators.validate_webhook_url, used by
/api/v1/webhooks) checked only the literal host, so a NAME that resolves to an internal address passed. And a
delivery sent to whatever the stored URL resolved to at that moment, so a URL stored before the check, or a name
whose address changed after it was stored, still reached the registry's own network (the answer is kept in the
delivery record its owner can read).

Now: both route pairs use the canonical validator; it resolves the host and refuses it when ANY address is
internal (private, loopback, link-local, metadata, IPv4-mapped...); a host that does not resolve is accepted (it
reaches nothing now) because every delivery and retry resolves the stored URL again and refuses an internal one.

Through FastAPI on the real routers; the developer, the database session and the resolver are doubles (no test
here touches the network: socket.getaddrinfo answers from a table, an unknown name fails as NXDOMAIN).
RED on 14520b9f: every internal-name case, the older routes' literal cases, and both delivery cases.
"""
import datetime as dt
import socket
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import developers, webhooks
from agentvault_registry.services.webhook_service import WebhookService

EVENT = WebhookService.SUPPORTED_EVENTS[0]
DNS = {
    "hooks.public.example": ["93.184.216.34"],
    "internal.example": ["10.1.2.3"],
    "loopback.example": ["127.0.0.1"],
    "mixed.example": ["93.184.216.34", "192.168.7.7"],
    "mapped.example": ["::ffff:127.0.0.1"],
    "metadata-alias.example": ["169.254.169.254"],
}
INTERNAL_NAMES = ["internal.example", "loopback.example", "mixed.example", "mapped.example", "metadata-alias.example"]


@pytest.fixture(autouse=True)
def resolver(monkeypatch):
    asked = []

    def getaddrinfo(host, port, *a, **k):
        asked.append(host)
        if host not in DNS:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        out = []
        for addr in DNS[host]:
            if ":" in addr:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, port, 0, 0)))
            else:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port)))
        return out

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return asked


def _hook(url="https://hooks.public.example/h"):
    return types.SimpleNamespace(id="wh-1", developer_id=7, url=url, events=[EVENT], secret="s" * 32,
                                 is_active=True, failure_count=0, created_at=dt.datetime.now(dt.timezone.utc),
                                 updated_at=None, last_triggered_at=None, description=None)


class _Res:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return types.SimpleNamespace(all=lambda: list(self.rows))

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []

    async def execute(self, stmt, params=None):
        return _Res([self.existing] if self.existing is not None else [])

    async def scalar(self, stmt):
        return 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = dt.datetime.now(dt.timezone.utc)


def _client(db):
    app = FastAPI()
    app.include_router(developers.router, prefix="/api/v1")
    app.include_router(webhooks.router)
    dev = types.SimpleNamespace(id=7, email="dev@example.test", is_admin=False)
    app.dependency_overrides[security.get_current_developer] = lambda: dev
    app.dependency_overrides[webhooks.get_current_developer] = lambda: dev

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


# ── the older pair: /api/v1/developers/webhooks ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [f"https://{n}/hook" for n in INTERNAL_NAMES]
                         + ["http://127.0.0.1:8000/x", "http://[::1]/x", "http://10.0.0.8/x", "ftp://hooks.public.example/x"])
def test_older_create_refuses_an_internal_or_unsafe_url(url):
    db = _Db()
    r = _client(db).post("/api/v1/developers/webhooks", json={"url": url, "events": [EVENT]})
    assert r.status_code == 400, (url, r.status_code, r.text)
    assert db.added == [], url


@pytest.mark.parametrize("url", ["https://hooks.public.example/hook", "https://later.invalid/hook"])
def test_older_create_accepts_a_public_or_not_yet_resolving_url(url):
    db = _Db()
    r = _client(db).post("/api/v1/developers/webhooks", json={"url": url, "events": [EVENT]})
    assert r.status_code == 201, (url, r.status_code, r.text)
    assert [w.url for w in db.added] == [url]


def test_older_update_refuses_an_internal_url():
    hook = _hook()
    r = _client(_Db(existing=hook)).put("/api/v1/developers/webhooks/wh-1", json={"url": "https://internal.example/h"})
    assert r.status_code == 400, (r.status_code, r.text)
    assert hook.url == "https://hooks.public.example/h"


# ── the canonical pair: /api/v1/webhooks ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", INTERNAL_NAMES)
def test_canonical_create_refuses_a_name_that_resolves_internal(name):
    db = _Db()
    r = _client(db).post("/api/v1/webhooks", json={"url": f"https://{name}/hook", "events": [EVENT]})
    assert r.status_code == 422, (name, r.status_code, r.text)
    assert db.added == []


def test_canonical_create_accepts_a_public_name(resolver):
    db = _Db()
    r = _client(db).post("/api/v1/webhooks", json={"url": "https://hooks.public.example/hook", "events": [EVENT]})
    assert r.status_code == 201, (r.status_code, r.text)
    assert "hooks.public.example" in resolver  # the control: the name WAS resolved


def test_canonical_update_refuses_a_name_that_resolves_internal():
    hook = _hook()
    r = _client(_Db(existing=hook)).put("/api/v1/webhooks/wh-1", json={"url": "https://loopback.example/h"})
    assert r.status_code == 422, (r.status_code, r.text)
    assert hook.url == "https://hooks.public.example/h"


# ── delivery: the stored URL is resolved again at the moment of sending ──────────────────────────────────────────

class _Client:
    def __init__(self):
        self.sent, self.kw = [], []

    async def post(self, url, **kw):
        self.sent.append(url)
        self.kw.append(kw)
        return types.SimpleNamespace(status_code=200, text="")


async def test_a_delivery_never_sends_to_a_name_that_resolves_internal():
    svc = WebhookService()
    svc.client = _Client()
    hook = _hook("https://internal.example/h")  # stored before the check, or re-pointed after it
    delivery = await svc.deliver_webhook(hook, EVENT, {"k": 1}, None, _Db())
    assert svc.client.sent == []
    assert "refused" in (delivery.error_message or ""), delivery.error_message


async def test_a_retry_never_sends_to_a_name_that_resolves_internal():
    svc = WebhookService()
    svc.client = _Client()
    hook = _hook("http://127.0.0.1:6379/")
    delivery = types.SimpleNamespace(id="d-1", event_type=EVENT, retry_count=0, delivered_at=None,
                                     payload={"id": "d-1", "event": EVENT, "data": {}, "timestamp": None,
                                              "agent_did": None},
                                     response_status=None, response_body=None, error_message=None,
                                     next_retry_at=None)
    await svc.retry_delivery(delivery, hook, _Db())
    assert svc.client.sent == []
    assert "refused" in (delivery.error_message or ""), delivery.error_message


async def test_control_a_delivery_to_a_public_name_is_sent():
    """Corrected for SEC-14 (2026-10-17): the delivery goes to the address its check approved, naming the host in its
    Host header and TLS server name. This control asserted the URL itself was handed to the client, which then looked
    the name up a second time: the window SEC-14 closes."""
    svc = WebhookService()
    svc.client = _Client()
    delivery = await svc.deliver_webhook(_hook(), EVENT, {"k": 1}, None, _Db())
    assert svc.client.sent == ["https://93.184.216.34/h"]
    assert svc.client.kw[0]["headers"]["Host"] == "hooks.public.example"
    assert svc.client.kw[0]["extensions"] == {"sni_hostname": "hooks.public.example"}
    assert delivery.response_status == 200
