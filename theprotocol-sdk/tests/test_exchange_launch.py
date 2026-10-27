"""§AGORAWORDS (0.7.2): ExchangeClient.launch_buy is the name; ipo_buy still works and warns. Hermetic via MockTransport."""
import json

import httpx
import pytest

from theprotocol.exchange.client import ExchangeClient


def _client(handler):
    c = ExchangeClient("https://reg.example")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


@pytest.mark.asyncio
async def test_launch_buy_posts_the_documented_path_on_a_current_registry():
    """0.7.3: /api/v1/agora (the probe answers 200), and the launch purchase under its own name."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"listings": []})
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers.get("authorization"), json.loads(request.content)
        return httpx.Response(200, json={"purchase_id": 7, "status": "pending", "qty": 5, "amount": "5"})

    c = _client(handler)
    out = await c.launch_buy("jwt-a", "ALFW", 5)
    await c.aclose()
    assert seen["url"] == "https://reg.example/api/v1/agora/listings/ALFW/launch/buy"
    assert seen["auth"] == "Bearer jwt-a" and seen["body"] == {"qty": 5}
    assert out["purchase_id"] == 7


@pytest.mark.asyncio
async def test_an_older_registry_is_spoken_to_under_the_old_path():
    """A registry before V0419 answers /api/v1/agora with a bare 404 "Not Found": the client keeps /api/v1/exchange
    for its life, and the launch purchase goes to that registry's ipo/buy."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if "/api/v1/agora/" in str(request.url):
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.method == "GET":
            return httpx.Response(200, json={"listings": [{"symbol": "ALFW"}]})
        return httpx.Response(200, json={"purchase_id": 9, "status": "pending", "qty": 1, "amount": "1"})

    c = _client(handler)
    rows = await c.listings()
    out = await c.launch_buy("jwt-a", "ALFW", 1)
    await c.aclose()
    assert c.base == "https://reg.example/api/v1/exchange"
    assert rows == [{"symbol": "ALFW"}] and out["purchase_id"] == 9
    assert seen == [("GET", "https://reg.example/api/v1/agora/listings"),
                    ("GET", "https://reg.example/api/v1/exchange/listings"),
                    ("POST", "https://reg.example/api/v1/exchange/listings/ALFW/ipo/buy")]


@pytest.mark.asyncio
async def test_an_unknown_listing_is_an_answer_not_an_older_registry():
    """A business 404 (the listing is unknown) keeps the documented path; the caller sees the 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/api/v1/agora/listings"):
            return httpx.Response(200, json={"listings": []})
        return httpx.Response(404, json={"detail": "listing 'NOPE' not found"})

    c = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await c.listing("NOPE")
    await c.aclose()
    assert c.base == "https://reg.example/api/v1/agora"


@pytest.mark.asyncio
async def test_ipo_buy_is_a_deprecated_alias_with_the_same_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"purchase_id": 8, "status": "pending", "qty": 2, "amount": "2"})

    c = _client(handler)
    with pytest.warns(DeprecationWarning, match="launch_buy"):
        out = await c.ipo_buy("jwt-a", "ALFW", 2)
    await c.aclose()
    assert out["purchase_id"] == 8
