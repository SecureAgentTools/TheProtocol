"""V0663 (order gwo_e3187dbb237a06e8261c1dfc, following V0662 item 14): the remaining outside images through the registry.

V0662 served agent card icons from the registry's own origin. Three kinds of image still loaded from wherever their
record said, in every reader's browser: peer registries' logos (an ACTIVE peer's signed card, visual.icon_url, made
absolute on the peer's origin), developer avatars (developers.avatar_url) and flare logos (developers.flare_logo_url,
and the flare a card carries, card_data.flare.logo_url, on a mirror as on a native card).

GET /api/v1/public/images?src=<address> serves them through the same guarded, cached path as the card icons
(services/card_icons: fetched once through the outbound guard, size and type bounded, rasters written again as PNG, SVG
rebuilt from the allowlist, nosniff and a sandbox CSP). It is not an open fetcher: an address is served only when one
of this registry's own records names it (services/outside_images.address_kind), and anything else answers 404 without
a fetch. The console draws these images only through it (its tests: outsideImageSites.test.ts).

And the 307 path of the card icon route, pinned as session-lead read it: a native card naming "/\\evil.com" is sent to
"/%5Cevil.com", a path on this origin.
Red on b27f2ebaf: services/outside_images and the route do not exist.
"""
from __future__ import annotations

import asyncio
import io

import httpx
import pytest
from PIL import Image

try:     # red as one failure per test, not a collection error that stops the suite
    from agentvault_registry.services import outside_images as oi
except ImportError:
    oi = None
from agentvault_registry.services import card_icons as ci


def test_the_module_exists():
    from agentvault_registry.services import outside_images
    from agentvault_registry.routers import outside_images as r
    assert callable(outside_images.address_kind) and r.router is not None


def _png():
    out = io.BytesIO()
    Image.new("RGBA", (40, 40), (10, 200, 30, 255)).save(out, "PNG")
    return out.getvalue()


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def delete(self, k):
        self.store.pop(k, None)


# --- which records name an address ---------------------------------------------------------------------------------

AVATAR = "https://pics.example.org/ann.png"
FLARE = "https://brand.example.org/flare.svg"
CARD_FLARE = "https://brand.example.org/agent-flare.png"
PEER = "https://asia.example.org/static/registry-cards/asia/icon.png"


def _lookups(*, developers=(), cards=(), peers=()):
    """The three record readers address_kind asks, as tables."""
    async def dev(db, url):
        return [k for k, v in developers if v == url]

    async def card(db, url):
        return [k for k, v in cards if v == url]

    async def peer(db, redis, url):
        return url in peers
    return {"developer_kinds": dev, "card_flare_named": card, "peer_icon_named": peer}


@pytest.mark.parametrize("url,want", [
    (AVATAR, "developer_avatar"),
    (FLARE, "flare_logo"),
    (CARD_FLARE, "flare_logo"),
    (PEER, "registry_logo"),
    ("https://elsewhere.example.org/x.png", None),
])
def test_an_address_is_served_only_when_a_record_names_it(monkeypatch, url, want):
    for name, fn in _lookups(developers=[("developer_avatar", AVATAR), ("flare_logo", FLARE)],
                             cards=[("flare_logo", CARD_FLARE)], peers=[PEER]).items():
        monkeypatch.setattr(oi, name, fn)
    assert asyncio.run(oi.address_kind(None, None, url)) == want


@pytest.mark.parametrize("url", ["/static/x.png", "//evil.example.org/x.png", "ftp://x.example.org/a.png",
                                 "javascript:alert(1)", "", "x" * 3000])
def test_an_address_that_is_not_absolute_http_or_data_is_never_looked_up(monkeypatch, url):
    asked = []

    async def dev(db, u):
        asked.append(u)
        return ["developer_avatar"]
    monkeypatch.setattr(oi, "developer_kinds", dev)
    assert asyncio.run(oi.address_kind(None, None, url)) is None and asked == []


def test_the_lookups_read_by_index_or_by_equality_and_only_read():
    from sqlalchemy.dialects import postgresql
    dev = str(oi.developer_kinds_stmt("https://a.example.org/x.png").compile(dialect=postgresql.dialect())).lower()
    assert dev.lstrip().startswith("select") and "avatar_url" in dev and "flare_logo_url" in dev
    card = str(oi.card_flare_stmt("https://a.example.org/x.png").compile(dialect=postgresql.dialect()))
    assert "@>" in card and "->>" not in card and "is_active" in card, "the GIN index on card_data serves it"
    for sql in (dev, card.lower()):
        for verb in ("insert ", "update ", "delete "):
            assert verb not in sql


# --- the route -----------------------------------------------------------------------------------------------------

def _app(monkeypatch, *, kind="developer_avatar", body=None, fail=None):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import outside_images as route

    fetched = []

    async def known(db, redis, url):
        return kind

    async def fetch(url):
        fetched.append(url)
        if fail:
            raise ci.IconUnavailable(fail)
        return body if body is not None else _png()

    r = FakeRedis()

    async def redis():
        return r
    monkeypatch.setattr(oi, "address_kind", known)
    monkeypatch.setattr(ci, "fetch_icon", fetch)
    monkeypatch.setattr(ci, "redis_handle", redis)
    app = FastAPI()
    app.include_router(route.router)

    class _Db:
        async def rollback(self):
            pass

    async def get_db():
        yield _Db()
    app.dependency_overrides[database.get_db] = get_db
    return app, fetched


def _get(app, path, headers=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.get(path, headers=headers or {})
    return asyncio.run(go())


def test_a_named_image_is_served_from_this_origin_with_the_card_icons_headers(monkeypatch):
    app, fetched = _app(monkeypatch)
    resp = _get(app, f"/api/v1/public/images?src={AVATAR}")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in resp.headers["content-security-policy"] and resp.headers.get("etag")
    assert fetched == [AVATAR]
    again = _get(app, f"/api/v1/public/images?src={AVATAR}", {"if-none-match": resp.headers["etag"]})
    assert again.status_code == 304
    assert fetched == [AVATAR], "fetched once: the second answer came from the cache"


def test_an_svg_flare_logo_is_served_rebuilt(monkeypatch):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>x</script><circle r="2"/></svg>'
    app, _ = _app(monkeypatch, kind="flare_logo", body=svg)
    resp = _get(app, f"/api/v1/public/images?src={FLARE}")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("image/svg+xml")
    assert b"script" not in resp.content and b"onload" not in resp.content


def test_an_address_no_record_names_answers_404_and_fetches_nothing(monkeypatch):
    app, fetched = _app(monkeypatch, kind=None)
    resp = _get(app, "/api/v1/public/images?src=https://elsewhere.example.org/x.png")
    assert resp.status_code == 404 and "not an image any record here names" in resp.json()["detail"]
    assert fetched == []


def test_an_image_that_cannot_be_served_says_why(monkeypatch):
    app, _ = _app(monkeypatch, fail="http_500")
    resp = _get(app, f"/api/v1/public/images?src={AVATAR}")
    assert resp.status_code == 404 and "http_500" in resp.json()["detail"]


def test_no_src_is_a_404_not_a_500(monkeypatch):
    app, fetched = _app(monkeypatch)
    assert _get(app, "/api/v1/public/images").status_code in (404, 422)
    assert fetched == []


# --- the card icon route's 307, as session-lead read it --------------------------------------------------------------

def test_a_native_cards_backslash_path_stays_on_this_origin(monkeypatch):
    """Session-lead (room seq 3285): Starlette encodes "/\\evil.com" as "/%5Cevil.com", a path on this origin; a browser
    that read "/\\evil.com" as a scheme-relative address would have left it."""
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import card_icons as route

    async def lookup(_db, did):
        return ("/\\evil.com", True)

    async def must_not_fetch(url):
        raise AssertionError("a native card's own path is never fetched")
    monkeypatch.setattr(ci, "card_icon_address", lookup)
    monkeypatch.setattr(ci, "fetch_icon", must_not_fetch)
    app = FastAPI()
    app.include_router(route.router, prefix="/api/v1/agent-cards")

    class _Db:
        async def rollback(self):
            pass

    async def get_db():
        yield _Db()
    app.dependency_overrides[database.get_db] = get_db
    resp = _get(app, "/api/v1/agent-cards/did:theprotocol:abc/icon")
    assert resp.status_code == 307
    loc = resp.headers["location"]
    assert loc == "/%5Cevil.com" and not loc.startswith("//") and "\\" not in loc


def test_a_registry_logo_is_this_registrys_own_or_a_peers_as_the_console_shows_them(monkeypatch):
    """This registry's own logo is absolute on its public host (not always the console's origin), the frame manifest
    names its peers' (registry-config carries it), and the federation views read every ACTIVE peer's entry."""
    from agentvault_registry.core import federation_view as fv
    OWN, MANIFEST_PEER, ENTRY_PEER = ("https://eu.example.org/static/registry-cards/eu/icon.png",
                                      "https://asia.example.org/static/registry-cards/asia/icon.png",
                                      "https://lisbon.example.org/static/registry-cards/lisbon/icon.png")

    async def manifest(db, redis=None, **k):
        return {"self": {"icon_url": OWN}, "peers": [{"icon_url": MANIFEST_PEER}, {"icon_url": None}]}

    async def entries(db, redis=None):
        return [{"icon_url": ENTRY_PEER}]
    monkeypatch.setattr(fv, "build_manifest", manifest)
    monkeypatch.setattr(fv, "active_peer_entries", entries)
    for url in (OWN, MANIFEST_PEER, ENTRY_PEER):
        assert asyncio.run(oi.peer_icon_named(None, None, url)) is True, url
    assert asyncio.run(oi.peer_icon_named(None, None, "https://elsewhere.example.org/x.png")) is False
