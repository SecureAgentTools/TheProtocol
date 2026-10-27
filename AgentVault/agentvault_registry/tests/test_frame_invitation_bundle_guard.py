"""§FINDINGS-A4 3d (2026-09-27, his "fix 1-4 approved"): the public invitation route's bundle dials.

`POST /federation/frame-invitations` is unauthenticated and dials the caller's `bundle_endpoint_url`. It followed redirects
(only the first URL had to be https) and echoed the probe's error, a status oracle from inside our network. Now an
anonymous caller reaches only PUBLIC https hosts on every hop and gets a generic refusal; a federation admin may name an
internal host (same-host frames federate over the compose network); at approve a public URL is never followed inward.
"""
import types

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.middleware.rate_limiter import shared_limiter
from agentvault_registry.routers import frame_invitations as fi
from agentvault_registry.services import frame_trust_manager as ftm

DNS = {"public.example.invalid": ["1.1.1.1"], "inside.example.invalid": ["10.0.0.9"],
       "mixed.example.invalid": ["1.1.1.1", "172.16.0.7"], "loop.example.invalid": ["127.0.0.1"]}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    async def resolve(host, port):
        if host not in DNS:
            raise OSError("no such host")
        return DNS[host]
    monkeypatch.setattr(ftm, "_resolve", resolve)


def _transport(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(ftm, "_bundle_client", lambda timeout: httpx.AsyncClient(
        transport=httpx.MockTransport(wrapped), timeout=timeout, follow_redirects=False))
    return seen


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.1.2.3", "172.16.0.7", "192.168.1.1", "169.254.1.1", "100.64.0.1",
                                  "0.0.0.0", "192.0.2.1", "224.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1"])
def test_every_non_global_address_is_internal(addr):
    assert ftm._address_is_internal(addr)


@pytest.mark.parametrize("addr", ["1.1.1.1", "9.9.9.9", "2606:4700:4700::1111"])
def test_control_global_addresses_are_public(addr):
    assert not ftm._address_is_internal(addr)


@pytest.mark.parametrize("host,internal", [("public.example.invalid", False), ("inside.example.invalid", True),
                                           ("mixed.example.invalid", True), ("gone.example.invalid", True),
                                           ("10.0.0.1", True), ("1.1.1.1", False), ("[::1]", True)])
async def test_a_name_is_internal_when_any_address_is_or_it_does_not_resolve(host, internal):
    assert (await ftm._host_is_internal(host, 443))[0] is internal


async def test_a_redirect_inward_is_refused_for_an_anonymous_dial_and_followed_for_an_admin(monkeypatch):
    def handler(request):
        if request.url.host == "public.example.invalid":
            return httpx.Response(302, headers={"location": "https://inside.example.invalid/bundle"})
        return httpx.Response(200, text="{}")
    seen = _transport(monkeypatch, handler)
    async with ftm._bundle_client(5) as c:
        r, refusal = await ftm._dial_checked(c, "GET", "https://public.example.invalid/", allow_internal=False)
    assert r is None and "internal" in refusal and seen == ["https://public.example.invalid/"]
    async with ftm._bundle_client(5) as c:
        r, refusal = await ftm._dial_checked(c, "GET", "https://public.example.invalid/", allow_internal=True)
    assert refusal is None and r.status_code == 200


async def test_a_redirect_to_plain_http_and_a_redirect_loop_are_refused(monkeypatch):
    def handler(request):
        if request.url.path == "/to-http":
            return httpx.Response(301, headers={"location": "http://public.example.invalid/"})
        return httpx.Response(302, headers={"location": "https://public.example.invalid/again"})
    _transport(monkeypatch, handler)
    async with ftm._bundle_client(5) as c:
        _, why = await ftm._dial_checked(c, "GET", "https://public.example.invalid/to-http", allow_internal=False)
        assert "https" in why
        _, why = await ftm._dial_checked(c, "GET", "https://public.example.invalid/loop", allow_internal=False)
        assert "redirects" in why


async def test_the_probe_dials_nothing_for_an_anonymous_internal_url(monkeypatch):
    seen = _transport(monkeypatch, lambda request: httpx.Response(200))
    mgr = ftm.FrameTrustManager.__new__(ftm.FrameTrustManager)
    ok, err = await mgr.probe_bundle_endpoint("https://inside.example.invalid:8443/")
    assert not ok and "internal" in err and seen == []
    ok, err = await mgr.probe_bundle_endpoint("https://inside.example.invalid:8443/", allow_internal=True)
    assert ok and err is None and seen


async def test_approve_never_follows_a_public_bundle_url_inward(monkeypatch):
    def handler(request):
        if request.url.host == "public.example.invalid":
            return httpx.Response(302, headers={"location": "https://loop.example.invalid/secret"})
        return httpx.Response(200, text='{"keys": ["an internal answer"]}')
    seen = _transport(monkeypatch, handler)
    mgr = ftm.FrameTrustManager.__new__(ftm.FrameTrustManager)
    body, _ct, err = await mgr.fetch_remote_bundle("https://public.example.invalid/bundle", "td.invalid")
    assert body is None and "internal" in err
    assert not any("loop.example.invalid" in u for u in seen)


@pytest.mark.parametrize("dev,expected", [
    (None, False),
    (types.SimpleNamespace(is_admin=False, admin_federation=False, must_change_password=False), False),
    (types.SimpleNamespace(is_admin=True, admin_federation=False, must_change_password=False), True),
    (types.SimpleNamespace(is_admin=False, admin_federation=True, must_change_password=False), True),
    (types.SimpleNamespace(is_admin=True, admin_federation=True, must_change_password=True), False),
])
def test_only_a_federation_admin_may_name_an_internal_bundle(dev, expected):
    assert fi._may_name_internal_bundle(dev) is expected


def test_control_a_narrow_api_key_does_not_rescue_an_admin(monkeypatch):
    monkeypatch.setattr(security, "api_key_grants_admin", lambda: False)
    assert fi._may_name_internal_bundle(types.SimpleNamespace(is_admin=True, admin_federation=True,
                                                              must_change_password=False)) is False


class _NoPending:
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None)


def _route_client(monkeypatch, caller):
    monkeypatch.setattr(shared_limiter, "enabled", False)
    app = FastAPI()
    app.state.limiter = shared_limiter
    app.include_router(fi.router)
    app.dependency_overrides[get_db] = lambda: _NoPending()
    app.dependency_overrides[security.get_current_developer_optional] = lambda: caller
    return TestClient(app, raise_server_exceptions=False)


INVITE = {"trust_domain": "stranger.example.invalid", "bundle_endpoint_url": "https://inside.example.invalid:8443/",
          "federation_endpoint_url": "https://inside.example.invalid:8444/", "name": "stranger",
          "contact_email": "nobody@example.invalid", "initiator_nonce": "ab" * 16}


def test_an_anonymous_internal_invitation_gets_a_generic_refusal_and_no_dial(monkeypatch):
    seen = _transport(monkeypatch, lambda request: httpx.Response(200))
    r = _route_client(monkeypatch, None).post("/api/v1/federation/frame-invitations", json=INVITE)
    assert r.status_code == 422, r.text[:300]
    text = r.text
    assert "public https address" in text
    assert "inside.example.invalid" not in text and "internal" not in text   # no oracle: neither the host nor the why
    assert seen == []
