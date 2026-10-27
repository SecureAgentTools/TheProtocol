"""Tests for theprotocol.guild.GuildClient (agent work exchange) — hermetic via MockTransport."""
import json

import httpx
import pytest

from theprotocol.guild import GuildClient, GuildError


def _client_with(handler):
    return GuildClient("https://reg.example", transport=httpx.MockTransport(handler))


# ── post / discover ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_order_body_uses_router_field_names():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"order_id": "gwo_abc", "status": "open",
                                         "bounty": 5.0, "currency": "BVT", "fee_bps": 250})

    c = _client_with(handler)
    out = await c.post_order("jwt-p", "Summarize X", "the spec", 5.0,
                             deadline_seconds=3600, min_reputation=10.0,
                             stake_required=1.0, required_skills=["nlp"])
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/guild/orders"
    assert captured["auth"] == "Bearer jwt-p"
    # Router truth: OrderPostIn uses deadline_seconds (NOT deadline)
    assert captured["body"] == {
        "title": "Summarize X", "spec": "the spec", "bounty": 5.0,
        "deadline_seconds": 3600, "min_reputation": 10.0,
        "stake_required": 1.0, "required_skills": ["nlp"],
    }
    assert out["order_id"] == "gwo_abc"


@pytest.mark.asyncio
async def test_post_order_escrow_failure_raises_guild_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"detail": "Escrow failed (insufficient balance?): broke"})

    c = _client_with(handler)
    with pytest.raises(GuildError) as ei:
        await c.post_order("jwt-p", "T", None, 500.0)
    await c.close()

    assert ei.value.status_code == 402
    assert "Escrow failed" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_list_orders_uses_status_filter_param_and_is_public():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"orders": [{"id": "gwo_1"}], "total": 1})

    c = _client_with(handler)
    out = await c.list_orders(status="awarded", limit=10)
    await c.close()

    # Router truth: the query param is status_filter (NOT status)
    assert captured["url"] == "https://reg.example/api/v1/guild/orders?limit=10&status_filter=awarded"
    assert captured["auth"] is None
    assert out["total"] == 1


@pytest.mark.asyncio
async def test_get_order_path():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"id": "gwo_1", "status": "open", "bids": []})

    c = _client_with(handler)
    out = await c.get_order("gwo_1")
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/guild/orders/gwo_1"
    assert out["status"] == "open"


# ── the work loop ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bid_posts_to_plural_bids_path():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"bid_id": 9, "status": "open"})

    c = _client_with(handler)
    out = await c.bid("jwt-w", "gwo_1", 4.0, eta_seconds=600, pitch="on it")
    await c.close()

    # Router truth: POST .../bids (plural), fields price/eta_seconds/pitch
    assert captured["url"] == "https://reg.example/api/v1/guild/orders/gwo_1/bids"
    assert captured["auth"] == "Bearer jwt-w"
    assert captured["body"] == {"price": 4.0, "eta_seconds": 600, "pitch": "on it"}
    assert out["bid_id"] == 9


@pytest.mark.asyncio
async def test_award_submit_verify_bodies():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "status": "settled"})

    c = _client_with(handler)
    await c.award("jwt-p", "gwo_1", bid_id=9)
    await c.submit("jwt-w", "gwo_1", {"text": "done", "uri": "ipfs://x"})
    await c.verify("jwt-p", "gwo_1", stars=4, feedback="solid")
    await c.close()

    assert calls[0] == ("https://reg.example/api/v1/guild/orders/gwo_1/award", {"bid_id": 9})
    assert calls[1] == ("https://reg.example/api/v1/guild/orders/gwo_1/submit",
                        {"deliverable": {"text": "done", "uri": "ipfs://x"}})
    # Router truth: VerifyIn is {accept, stars, feedback} — stars is the rating
    assert calls[2] == ("https://reg.example/api/v1/guild/orders/gwo_1/verify",
                        {"accept": True, "stars": 4, "feedback": "solid"})


@pytest.mark.asyncio
async def test_verify_reject_opens_dispute_and_conflict_raises():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(409, json={"detail": "Order is settled"})

    c = _client_with(handler)
    with pytest.raises(GuildError) as ei:
        await c.verify("jwt-p", "gwo_1", accept=False)
    await c.close()

    assert captured["body"] == {"accept": False, "stars": 5}
    assert ei.value.status_code == 409


# ── my desk / network / helper ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_my_work_hits_mine_and_network_board_public():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json={"orders": [], "total": 0})

    c = _client_with(handler)
    await c.my_work("jwt-w")
    await c.network_board()
    await c.close()

    # Router truth: GET /api/v1/guild/mine (NOT /my-work)
    assert calls[0] == ("https://reg.example/api/v1/guild/mine", "Bearer jwt-w")
    assert calls[1] == ("https://reg.example/api/v1/guild/network-board", None)


def test_eval_bounty_spec_header_format():
    # First line must be exactly eval_bounty://<suite_id>/<min_score> (router parses line 1)
    spec = GuildClient.eval_bounty_spec(3, 0.8, "Beat 80% on forge-code-v1")
    lines = spec.splitlines()
    assert lines[0] == "eval_bounty://3/0.8"
    assert lines[1] == "Beat 80% on forge-code-v1"

    bare = GuildClient.eval_bounty_spec(12, 0.55)
    assert bare == "eval_bounty://12/0.55"
    # Round-trips through the router's parser convention: int(sid), float(ms)
    sid, ms = bare[len("eval_bounty://"):].split("/", 1)
    assert int(sid) == 12 and float(ms) == 0.55
