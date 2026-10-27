"""§MCPTEST30 (2026-10-01) — a NUL character in a request path or query string is refused at the edge, 400.

Postgres refuses a NUL in any text value, so a route that handed one to its SQL unchecked answered 500: the MCP
tester's hostile-input probe measured `GET /api/v1/discover?query=...%00...` and `GET /api/v1/fiat/flare/agent/...%00...`
both at 500 on sbx-alpha (V0515), with no login. middleware/nul_refusal.py refuses the class for every route at once.
"""
from __future__ import annotations

import asyncio
import pathlib

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agentvault_registry.middleware import nul_refusal
from agentvault_registry.middleware.nul_refusal import NUL_REFUSAL_DETAIL, NulRefusalMiddleware, nul_in


def _app():
    async def item(request):
        return PlainTextResponse(f"item {len(request.path_params['key'])}")

    async def items(request):
        return PlainTextResponse(f"items {len(request.query_params.get('q', ''))}")

    app = Starlette(routes=[Route("/items", items), Route("/items/{key}", item)])
    app.add_middleware(NulRefusalMiddleware)
    return app


def test_where_a_nul_sits_is_read_decoded_and_raw():
    assert nul_in({"path": "/items/a\x00b", "raw_path": b"/items/a%00b", "query_string": b""}) == "path"
    assert nul_in({"path": "/items/ab", "raw_path": b"/items/a%00b", "query_string": b""}) == "path"
    assert nul_in({"path": "/items", "raw_path": b"/items", "query_string": b"q=a%00b"}) == "query"
    assert nul_in({"path": "/items", "raw_path": b"/items", "query_string": b"q=a\x00b"}) == "query"
    # the text "%00" sent encoded (%2500) is a literal percent sign followed by two zeros, not a NUL
    assert nul_in({"path": "/items", "raw_path": b"/items", "query_string": b"q=a%2500b"}) == ""
    assert nul_in({"path": "/items/x", "raw_path": b"/items/x", "query_string": b"q=%5C%25_"}) == ""


def test_a_nul_in_the_query_or_the_path_is_refused_400_before_the_route():
    c = TestClient(_app())
    for url in ("/items?q=a%00b", "/items/a%00b"):
        r = c.get(url)
        assert r.status_code == 400, (url, r.status_code)
        assert r.headers["content-type"].startswith("application/problem+json")
        body = r.json()
        assert body["detail"] == NUL_REFUSAL_DETAIL and body["status"] == 400
        assert body["error"]["context"]["where"] in ("query", "path")


def test_everything_else_passes_untouched():
    c = TestClient(_app())
    assert c.get("/items?q=a%2500b").text == "items 5"   # the five characters a%00b
    assert c.get("/items?q=%25_%5C").text == "items 3"
    assert c.get("/items/" + "p" * 300).text == "item 300"


def test_a_websocket_scope_is_passed_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    mw = NulRefusalMiddleware(inner)
    asyncio.run(mw({"type": "websocket", "path": "/ws/a\x00b", "raw_path": b"/ws/a%00b", "query_string": b""}, None, None))
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert seen == ["websocket", "lifespan"]


def test_the_refusal_is_counted_by_where():
    if nul_refusal.NUL_REFUSED_TOTAL is None:
        return
    before = nul_refusal.NUL_REFUSED_TOTAL.labels("query")._value.get()
    TestClient(_app()).get("/items?q=%00")
    assert nul_refusal.NUL_REFUSED_TOTAL.labels("query")._value.get() == before + 1


def test_the_registry_registers_it_outside_the_freeze_and_inside_cors():
    main = (pathlib.Path(nul_refusal.__file__).parent.parent / "main.py").read_text()
    assert main.count("app.add_middleware(NulRefusalMiddleware)") == 1
    at = main.index("app.add_middleware(NulRefusalMiddleware)")
    # Starlette wraps the LAST added middleware outermost: after the freeze means outside it, before CORS inside it
    assert main.index("app.add_middleware(ReadOnlyModeMiddleware)") < at < main.index("_federation_cors.install(app)", at)
