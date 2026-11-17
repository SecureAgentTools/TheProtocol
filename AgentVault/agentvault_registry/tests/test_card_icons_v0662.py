"""V0662, item 14 (order gwo_d721ad2f8118863d62815103; PLAN_2026-11-13_DELIVERY_OUTBOUND_PACKAGE.md): card icons
served through the registry.

A card's iconUrl was loaded by every reader's browser from wherever the card said. Now the registry fetches it once,
through the one outbound guard (site card_icon), keeps it in Redis, and serves it from its own origin at
GET /api/v1/agent-cards/{did}/icon; the console loads icons only from there (its own tests:
services/agentAvatar.test.ts and cardIconSites.test.ts).

What the registry serves is never the fetched bytes as they came:
  - a raster image (PNG, JPEG, GIF, WebP, ICO, told by its bytes, never by the header) is decoded and written again as
    a PNG no larger than 256 px a side; anything else is refused, and so is an image that declares more pixels than
    the decoder is allowed to take;
  - an SVG is parsed without a DTD or entities and rebuilt from an allowlist of drawing elements: no script, no event
    handler, no reference outside the document, no style that loads anything;
  - a body over the size limit is refused while it streams, before it is all read;
  - the response says what it is (nosniff) and, opened on its own, runs nothing (a sandboxing CSP).
A failure is cached as well (shorter), so a broken icon is not fetched again on every page view, and a second worker
waits for the first one's fetch instead of starting its own. Red on c2011f54c: the module and the route do not exist.
"""
from __future__ import annotations

import asyncio
import base64
import io
import socket
import struct
import zlib

import httpx
import pytest
from PIL import Image

from agentvault_registry.core import outbound_guard as og

try:     # red as one failure per test, not a collection error that stops the suite
    from agentvault_registry.services import card_icons as ci
except ImportError:
    ci = None
PUBLIC = "93.184.216.34"   # a public address the export allows in a shipped file


def test_the_module_exists():
    from agentvault_registry.services import card_icons
    from agentvault_registry.routers import card_icons as _r
    assert card_icons.SITE == "card_icon" and _r.router is not None


# --- fixtures --------------------------------------------------------------------------------------------------------

class _Dns:
    def __init__(self):
        self.answers = {}

    def __call__(self, host, port, *a, **k):
        addrs = self.answers.get(host)
        if not addrs:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, port)) for x in addrs]


@pytest.fixture
def dns(monkeypatch):
    d = _Dns()
    monkeypatch.setattr(socket, "getaddrinfo", d)
    return d


class FakeRedis:
    """The calls card_icons makes: get, set (nx, ex), delete. Values kept as the str they were given."""

    def __init__(self):
        self.store, self.ttl, self.sets = {}, {}, 0

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k], self.ttl[k] = v, ex
        self.sets += 1
        return True

    async def delete(self, k):
        self.store.pop(k, None)
        return 1


def _png(w=32, h=32, color=(200, 30, 30, 255), fmt="PNG"):
    img = Image.new("RGBA" if fmt in ("PNG", "WEBP", "ICO") else "RGB", (w, h), color if fmt in ("PNG", "WEBP", "ICO") else color[:3])
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png_claiming(w, h):
    """A PNG whose header declares w x h; its data is a few bytes. A decoder that believes the header allocates w*h."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"\x00" * 16))
            + _chunk(b"IEND", b""))


def _refused(site, reason):
    c = og.OUTBOUND_REFUSED_TOTAL
    return c.labels(site=site, reason=reason)._value.get() if c is not None else 0.0


# --- what is served: rasters ----------------------------------------------------------------------------------------

def test_a_png_is_written_again_as_a_png_no_larger_than_256_a_side():
    icon = ci.normalise(_png(1000, 600))
    assert icon.content_type == "image/png"
    out = Image.open(io.BytesIO(icon.body))
    assert out.format == "PNG" and max(out.size) == 256 and out.size[1] < 256


@pytest.mark.parametrize("fmt", ["JPEG", "GIF", "WEBP", "ICO"])
def test_every_accepted_raster_comes_out_a_png(fmt):
    icon = ci.normalise(_png(48, 48, fmt=fmt))
    assert icon.content_type == "image/png"
    assert Image.open(io.BytesIO(icon.body)).format == "PNG"


@pytest.mark.parametrize("body", [
    b"<html><script>alert(1)</script></html>",
    b"%PDF-1.4 not an icon",
    b"%!PS-Adobe-3.0 EPSF-3.0\n",          # a format the decoder must never be offered (EPS runs a renderer)
    b"",
])
def test_bytes_that_are_not_an_accepted_image_are_refused(body):
    with pytest.raises(ci.IconUnavailable) as e:
        ci.normalise(body)
    assert e.value.reason == "not_an_image"


def test_an_image_declaring_more_pixels_than_allowed_is_refused_before_it_is_decoded():
    with pytest.raises(ci.IconUnavailable) as e:
        ci.normalise(_png_claiming(30000, 30000))
    assert e.value.reason == "too_many_pixels"


# --- what is served: SVG --------------------------------------------------------------------------------------------

SVG_NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def _svg(inner, attrs=""):
    return f'<svg {SVG_NS} viewBox="0 0 10 10" {attrs}>{inner}</svg>'.encode()


def test_an_svg_loses_its_scripts_handlers_and_outside_references():
    raw = _svg(
        '<script>alert(1)</script>'
        '<rect width="10" height="10" onclick="alert(2)" fill="red"/>'
        '<a href="https://evil.example.org/"><circle r="2"/></a>'
        '<image href="https://tracker.example.org/p.png" width="1" height="1"/>'
        '<use xlink:href="https://evil.example.org/s.svg#x"/>'
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>'
        '<set attributeName="href" to="javascript:alert(3)"/>'
        '<rect style="fill:url(https://tracker.example.org/f)" width="1" height="1"/>'
        '<style>@import url(https://evil.example.org/x.css);</style>',
        attrs='onload="alert(4)"')
    icon = ci.normalise(raw)
    assert icon.content_type == "image/svg+xml"
    out = icon.body.decode()
    for gone in ("script", "alert", "onclick", "onload", "evil.example.org", "tracker.example.org", "foreignObject",
                 "<image", "<a ", "<set", "@import", "javascript"):
        assert gone not in out, f"{gone!r} survived the sanitiser: {out}"
    assert "<rect" in out and 'fill="red"' in out, "the drawing itself is kept"


def test_an_svg_keeps_its_shapes_gradients_and_inside_references():
    raw = _svg(
        '<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient>'
        '<path id="p" d="M0 0L10 10"/></defs>'
        '<rect width="10" height="10" fill="url(#g)"/>'
        '<use xlink:href="#p"/>'
        '<style>.a{fill:#123456}</style><circle class="a" r="3"/>'
        '<title>logo</title>')
    out = ci.normalise(raw).body.decode()
    for kept in ('fill="url(#g)"', 'href="#p"', "linearGradient", ".a{fill:#123456}", "<circle", "<title>logo</title>"):
        assert kept in out, f"{kept!r} was lost: {out}"


@pytest.mark.parametrize("raw", [
    b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "xxxxxxxx">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    b'<!DOCTYPE svg SYSTEM "https://evil.example.org/x.dtd"><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<html xmlns="http://www.w3.org/1999/xhtml"><svg xmlns="http://www.w3.org/2000/svg"/></html>',
    b'<svg><rect width="1" height="1"/></svg>',     # no SVG namespace: no browser draws it as an image
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect',  # not well-formed
])
def test_an_svg_with_a_dtd_or_another_root_is_refused(raw):
    with pytest.raises(ci.IconUnavailable) as e:
        ci.normalise(raw)
    assert e.value.reason in ("svg_refused", "not_an_image")


def test_a_css_escape_cannot_hide_a_url():
    out = ci.normalise(_svg('<style>.a{background:\\75 rl(https://evil.example.org/x)}</style><circle r="1"/>')).body
    assert b"evil.example.org" not in out


# --- the fetch: through the guard ----------------------------------------------------------------------------------

def _wire(routes, seen=None):
    """routes: address -> (status, headers, body, stream?). Records the address each request reached."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append({"host": request.url.host, "hostname": request.headers.get("host")})
        status, headers, body = routes[request.url.host][:3]
        if len(routes[request.url.host]) > 3:     # a body that only streams (no Content-Length)
            async def gen():
                for i in range(0, len(body), 4096):
                    yield body[i:i + 4096]
            return httpx.Response(status, headers=headers, content=gen())
        return httpx.Response(status, headers=headers, content=body)
    return httpx.MockTransport(handler)


def test_a_name_that_resolves_private_is_refused_at_the_connection_and_counted(dns):
    dns.answers["icons.example.org"] = ["10.1.2.3"]
    seen = []
    before = _refused("card_icon", "private")
    with pytest.raises(ci.IconUnavailable) as e:
        asyncio.run(ci.fetch_icon("https://icons.example.org/a.png", inner=_wire({}, seen)))
    assert e.value.reason.startswith("refused")
    assert seen == [], "nothing may be sent once the guard refuses"
    assert _refused("card_icon", "private") == before + 1


def test_a_public_icon_is_fetched_at_the_checked_address(dns):
    dns.answers["icons.example.org"] = [PUBLIC]
    seen, body = [], _png()
    got = asyncio.run(ci.fetch_icon("https://icons.example.org/a.png",
                                    inner=_wire({PUBLIC: (200, {"content-type": "image/png"}, body)}, seen)))
    assert got == body
    assert seen[0]["host"] == PUBLIC and seen[0]["hostname"] == "icons.example.org"


def test_redirects_are_followed_twice_at_most_and_each_hop_is_checked(dns):
    dns.answers["a.example.org"] = [PUBLIC]
    dns.answers["b.example.org"] = ["93.184.216.35"]
    dns.answers["inside.example.org"] = ["192.168.7.7"]
    body = _png()
    ok = _wire({PUBLIC: (302, {"location": "https://b.example.org/i.png"}, b""),
                "93.184.216.35": (200, {}, body)})
    assert asyncio.run(ci.fetch_icon("https://a.example.org/i.png", inner=ok)) == body

    to_inside = _wire({PUBLIC: (302, {"location": "https://inside.example.org/i.png"}, b"")})
    with pytest.raises(ci.IconUnavailable) as e:
        asyncio.run(ci.fetch_icon("https://a.example.org/i.png", inner=to_inside))
    assert e.value.reason.startswith("refused")

    dns.answers["loop.example.org"] = ["93.184.216.36"]
    loop = _wire({"93.184.216.36": (302, {"location": "/again"}, b"")})
    with pytest.raises(ci.IconUnavailable) as e:
        asyncio.run(ci.fetch_icon("https://loop.example.org/i.png", inner=loop))
    assert e.value.reason == "redirect_limit"


def test_a_body_over_the_limit_is_refused_while_it_streams(dns, monkeypatch):
    monkeypatch.setattr(ci, "MAX_BYTES", 10_000)
    dns.answers["big.example.org"] = [PUBLIC]
    streamed = _wire({PUBLIC: (200, {}, b"\x00" * 50_000, "stream")})
    with pytest.raises(ci.IconUnavailable) as e:
        asyncio.run(ci.fetch_icon("https://big.example.org/i.png", inner=streamed))
    assert e.value.reason == "too_large"
    declared = _wire({PUBLIC: (200, {"content-length": "50000"}, b"\x00" * 50_000)})
    with pytest.raises(ci.IconUnavailable) as e:
        asyncio.run(ci.fetch_icon("https://big.example.org/i.png", inner=declared))
    assert e.value.reason == "too_large"


def test_a_status_other_than_200_is_unavailable(dns):
    dns.answers["gone.example.org"] = [PUBLIC]
    with pytest.raises(ci.IconUnavailable) as e:
        asyncio.run(ci.fetch_icon("https://gone.example.org/i.png", inner=_wire({PUBLIC: (404, {}, b"no")})))
    assert e.value.reason == "http_404"


def test_only_http_and_https_are_fetched(dns):
    for url in ("ftp://icons.example.org/a.png", "file:///etc/passwd", "javascript:alert(1)"):
        with pytest.raises(ci.IconUnavailable):
            asyncio.run(ci.fetch_icon(url, inner=_wire({})))


# --- the cache ------------------------------------------------------------------------------------------------------

def test_an_icon_is_fetched_once_and_then_served_from_the_cache():
    r, calls, body = FakeRedis(), [], _png()

    async def fetch(url):
        calls.append(url)
        return body

    async def go():
        a = await ci.icon_for_url("https://icons.example.org/a.png", redis=r, fetch=fetch)
        b = await ci.icon_for_url("https://icons.example.org/a.png", redis=r, fetch=fetch)
        return a, b
    a, b = asyncio.run(go())
    assert calls == ["https://icons.example.org/a.png"], "the second reader must not fetch again"
    assert a == b and a.content_type == "image/png"
    key = ci.cache_key("https://icons.example.org/a.png")
    assert r.ttl[key] == ci.CACHE_SEC and not any(k.endswith(":lock") for k in r.store), "the lock is released"


def test_a_failure_is_cached_for_a_shorter_time():
    r, calls = FakeRedis(), []

    async def fetch(url):
        calls.append(url)
        raise ci.IconUnavailable("http_500")

    async def go():
        for _ in range(3):
            with pytest.raises(ci.IconUnavailable) as e:
                await ci.icon_for_url("https://icons.example.org/broken.png", redis=r, fetch=fetch)
            assert e.value.reason == "http_500"
    asyncio.run(go())
    assert len(calls) == 1
    assert r.ttl[ci.cache_key("https://icons.example.org/broken.png")] == ci.FAIL_CACHE_SEC < ci.CACHE_SEC


def test_a_changed_icon_url_is_fetched_anew():
    r, calls = FakeRedis(), []

    async def fetch(url):
        calls.append(url)
        return _png()

    async def go():
        await ci.icon_for_url("https://icons.example.org/v1.png", redis=r, fetch=fetch)
        await ci.icon_for_url("https://icons.example.org/v2.png", redis=r, fetch=fetch)
    asyncio.run(go())
    assert len(calls) == 2


def test_a_second_reader_waits_for_the_first_fetch_instead_of_starting_its_own(monkeypatch):
    monkeypatch.setattr(ci, "POLL_SEC", 0.02)
    r, calls = FakeRedis(), []
    url = "https://icons.example.org/slow.png"

    async def fetch(u):
        calls.append(u)
        await asyncio.sleep(0.15)
        return _png()

    async def go():
        return await asyncio.gather(ci.icon_for_url(url, redis=r, fetch=fetch),
                                    ci.icon_for_url(url, redis=r, fetch=fetch))
    a, b = asyncio.run(go())
    assert len(calls) == 1 and a == b


def test_without_redis_nothing_is_fetched():
    """No cache means one outbound fetch per page view, per reader: refused instead."""
    calls = []

    async def fetch(u):
        calls.append(u)
        return _png()
    with pytest.raises(ci.IconUnavailable) as e:
        asyncio.run(ci.icon_for_url("https://icons.example.org/a.png", redis=None, fetch=fetch))
    assert e.value.reason == "cache_unavailable" and calls == []


def test_a_data_url_is_decoded_here_and_never_fetched():
    r, calls = FakeRedis(), []

    async def fetch(u):
        calls.append(u)
        return b""
    url = "data:image/png;base64," + base64.b64encode(_png()).decode()
    icon = asyncio.run(ci.icon_for_url(url, redis=r, fetch=fetch))
    assert icon.content_type == "image/png" and calls == []


# --- the card's address ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("card,want", [
    ({"iconUrl": " https://i.example.org/a.png "}, "https://i.example.org/a.png"),
    ({"icon_url": "https://i.example.org/b.png"}, "https://i.example.org/b.png"),
    ({"iconUrl": ""}, None),
    ({"iconUrl": None}, None),
    ({"iconUrl": 5}, None),
    ({}, None),
])
def test_the_icon_address_is_read_from_the_card(card, want):
    assert ci.icon_address(card) == want


def test_the_mirror_lookup_uses_the_card_index():
    """A mirrored card names its DID inside card_data; the lookup must be a jsonb containment (the GIN index on
    card_data serves it), never a ->> comparison that scans every card."""
    from sqlalchemy.dialects import postgresql
    sql = str(ci.mirror_card_stmt("did:theprotocol:x").compile(dialect=postgresql.dialect()))
    assert "@>" in sql and "->>" not in sql and "is_active" in sql
    native = str(ci.native_card_stmt("did:theprotocol:x").compile(dialect=postgresql.dialect()))
    assert "agent_did" in native and "is_active" in native


# --- the route ------------------------------------------------------------------------------------------------------

class _Db:
    def __init__(self):
        self.ended = 0

    async def rollback(self):
        self.ended += 1

    async def close(self):
        pass


def _app(monkeypatch, *, card=("https://icons.example.org/a.png", True), body=None, fail=None):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import card_icons as route

    db = _Db()
    r = FakeRedis()

    async def lookup(_db, did):
        return card

    async def fetch(url):
        if fail:
            raise ci.IconUnavailable(fail)
        return body if body is not None else _png()

    async def redis():
        return r
    monkeypatch.setattr(ci, "card_icon_address", lookup)
    monkeypatch.setattr(ci, "fetch_icon", fetch)
    monkeypatch.setattr(ci, "redis_handle", redis)
    app = FastAPI()
    app.include_router(route.router, prefix="/api/v1/agent-cards")

    async def get_db():
        yield db
    app.dependency_overrides[database.get_db] = get_db
    return app, db


def _get(app, path, headers=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.get(path, headers=headers or {})
    return asyncio.run(go())


def test_the_route_serves_the_icon_from_this_origin_with_safe_headers(monkeypatch):
    app, db = _app(monkeypatch)
    resp = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff"
    csp = resp.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp
    assert "max-age=" in resp.headers["cache-control"] and resp.headers.get("etag")
    assert db.ended >= 1, "the read transaction ends before the outbound fetch, so no pooled connection waits on it"
    again = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon", {"if-none-match": resp.headers["etag"]})
    assert again.status_code == 304 and again.content == b""


def test_an_svg_is_served_sanitised_as_svg(monkeypatch):
    app, _ = _app(monkeypatch, body=_svg('<script>x</script><circle r="1"/>'))
    resp = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("image/svg+xml")
    assert b"script" not in resp.content


def test_a_card_without_an_icon_answers_404(monkeypatch):
    app, _ = _app(monkeypatch, card=None)
    resp = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon")
    assert resp.status_code == 404 and "no icon" in resp.json()["detail"]


def test_an_icon_that_cannot_be_served_answers_404_and_says_why(monkeypatch):
    app, _ = _app(monkeypatch, fail="http_500")
    resp = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon")
    assert resp.status_code == 404 and "http_500" in resp.json()["detail"]


def test_a_native_cards_own_path_is_served_by_this_origin_without_a_fetch(monkeypatch):
    app, _ = _app(monkeypatch, card=("/static/pwa-192.png", True), fail="must_not_fetch")
    resp = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon")
    assert resp.status_code == 307 and resp.headers["location"] == "/static/pwa-192.png"


@pytest.mark.parametrize("card", [("/static/pwa-192.png", False), ("//evil.example.org/x.png", True),
                                  ("icons/x.png", True)])
def test_a_relative_address_that_is_not_this_origins_own_path_is_not_served(monkeypatch, card):
    app, _ = _app(monkeypatch, card=card, fail="must_not_fetch")
    resp = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon")
    assert resp.status_code == 404


def test_a_path_that_is_not_a_did_answers_404_without_a_lookup(monkeypatch):
    app, _ = _app(monkeypatch)
    assert _get(app, "/api/v1/agent-cards/not-a-did/icon").status_code == 404
