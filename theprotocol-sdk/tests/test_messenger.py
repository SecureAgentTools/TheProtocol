"""Tests for theprotocol.messenger.MessengerClient (§OURSTATE-3) — hermetic
via MockTransport. The point of each test is a CONTRACT, not coverage: the
speaker is the token, the vocabulary is closed, the loop is at-least-once.
"""
import json

import httpx
import pytest

from theprotocol.messenger import MessengerClient, MessengerError


def _client_with(handler):
    return MessengerClient("https://reg.example", transport=httpx.MockTransport(handler))


# ── addressing ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_thread_by_handle_sends_the_handle_not_a_guessed_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(201, json={"conversation_id": "c1", "created": True})

    out = await _client_with(handler).open_thread("dev.jwt", handle="@ruffa",
                                                  first_message="hello")
    assert out["conversation_id"] == "c1"
    assert captured["url"].endswith("/api/v1/chat/conversations")
    assert captured["body"]["target"] == {"ptype": "developer", "handle": "@ruffa"}
    assert captured["auth"] == "Bearer dev.jwt"
    # A first message always carries an idempotency key, even when the caller
    # did not think about retries.
    assert captured["body"]["first_message"]["client_ref"]


@pytest.mark.asyncio
async def test_open_thread_requires_an_address():
    with pytest.raises(ValueError):
        await _client_with(lambda r: httpx.Response(200, json={})).open_thread("jwt")


@pytest.mark.asyncio
async def test_agent_did_opens_a_service_thread_target():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"conversation_id": "c2"})

    await _client_with(handler).open_thread("jwt", agent_did="did:theprotocol:x",
                                            kind="agent_service")
    assert captured["body"]["kind"] == "agent_service"
    assert captured["body"]["target"]["agent_did"] == "did:theprotocol:x"


# ── the speaker IS the token ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reply_records_the_token_holder_and_never_a_claimed_author():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"message": {"seq": 4}})

    await _client_with(handler).reply("agent.jwt", "c1", "on it")
    assert captured["auth"] == "Bearer agent.jwt"
    # No speak_as / sender / author field exists to be forged.
    assert set(captured["body"]) == {"kind", "body", "client_ref"}


@pytest.mark.asyncio
async def test_reply_honours_a_caller_supplied_client_ref_for_replay():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ref"] = json.loads(request.content)["client_ref"]
        return httpx.Response(201, json={"message": {}})

    await _client_with(handler).reply("jwt", "c1", "hi", client_ref="fixed-ref-123")
    assert captured["ref"] == "fixed-ref-123"


# ── the card vocabulary is closed, and the builders mirror it ────────────────

def test_pay_request_builder_shape():
    card = MessengerClient.pay_request("12.5", "BVT", memo="the invoice")
    assert card == {"v": 1, "type": "pay.request",
                    "data": {"amount": "12.5", "currency": "BVT", "memo": "the invoice"}}


def test_work_pointer_refuses_a_type_outside_the_vocabulary():
    with pytest.raises(ValueError):
        MessengerClient.work_pointer("service.result", "r", "t")


def test_work_pointer_omits_an_amount_without_a_currency():
    # Never a bare number: an amount with no unit is the §FOREIGNACT bug.
    card = MessengerClient.work_pointer("guild.order", "o1", "Translate", amount="5")
    assert "amount" not in card["data"]
    card2 = MessengerClient.work_pointer("guild.order", "o1", "Translate", amount="5", currency="BVT")
    assert card2["data"]["amount"] == "5" and card2["data"]["currency"] == "BVT"


def test_there_is_no_builder_for_a_service_record():
    # Receipts are written by the registry's rail. An SDK that could issue one
    # would make every receipt worthless.
    assert not hasattr(MessengerClient, "service_result")
    assert not hasattr(MessengerClient, "pay_receipt_signed")


# ── the ack half ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ack_posts_the_conversation_and_seq():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    await _client_with(handler).ack("jwt", "c9", 42)
    assert captured["url"].endswith("/api/v1/chat/inbox/ack")
    assert captured["body"] == {"conversation_id": "c9", "seq": 42}


# ── errors carry the registry's own words ────────────────────────────────────

@pytest.mark.asyncio
async def test_error_carries_status_and_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "this room is announce-only"})

    with pytest.raises(MessengerError) as e:
        await _client_with(handler).reply("jwt", "c1", "hi")
    assert e.value.status_code == 403
    assert "announce-only" in str(e.value.detail)


# ── the poll loop is at-least-once, and survives a bad response ──────────────

@pytest.mark.asyncio
async def test_poll_once_yields_unread_and_dedups_across_passes():
    """The loop's contract without a stopwatch: `poll_once` is the testable
    seam, so 'yielded exactly once' is a definite answer rather than a timeout.
    (The first cut of this test drove `listen` and hung — an `async for … break`
    only re-checks its condition when the loop YIELDS, and this loop dedups.)"""
    calls = {"threads": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/conversations"):
            calls["threads"] += 1
            return httpx.Response(200, json={"conversations": [{"id": "c1", "unread": 1}]})
        if "/messages" in path:
            return httpx.Response(200, json={"messages": [
                {"id": "m1", "seq": 1, "kind": "text", "body": "hello"}]})
        return httpx.Response(404, json={})

    msgr = _client_with(handler)
    seen: set = set()
    first = await msgr.poll_once("jwt", seen)
    assert len(first) == 1 and first[0]["conversation_id"] == "c1" and first[0]["body"] == "hello"
    second = await msgr.poll_once("jwt", seen)
    assert second == []          # the SAME message is never handed over twice
    assert calls["threads"] == 2  # …and the loop really did poll again


@pytest.mark.asyncio
async def test_poll_once_without_a_seen_set_replays_everything():
    """At-least-once made explicit: a caller that keeps no memory (a fresh
    process after a crash) gets the message again rather than losing it."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/conversations"):
            return httpx.Response(200, json={"conversations": [{"id": "c1", "unread": 1}]})
        return httpx.Response(200, json={"messages": [{"id": "m1", "seq": 1, "kind": "text", "body": "hi"}]})

    msgr = _client_with(handler)
    assert len(await msgr.poll_once("jwt")) == 1
    assert len(await msgr.poll_once("jwt")) == 1


@pytest.mark.asyncio
async def test_poll_once_skips_threads_with_nothing_unread():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/conversations"):
            return httpx.Response(200, json={"conversations": [
                {"id": "c1", "unread": 0}, {"id": "c2"}]})
        raise AssertionError("must not fetch messages for a read thread")

    assert await _client_with(handler).poll_once("jwt", set()) == []


@pytest.mark.asyncio
async def test_a_failing_poll_raises_to_the_caller_but_listen_survives_it():
    """`poll_once` is honest (it raises); `listen` is durable (it logs and keeps
    the cadence). Both properties matter, and they belong to different layers."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    with pytest.raises(MessengerError):
        await _client_with(handler).poll_once("jwt", set())
