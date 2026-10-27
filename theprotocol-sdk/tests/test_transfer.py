"""Tests for theprotocol.transfer.TransferClient (smart send) — hermetic via MockTransport."""
import json

import httpx
import pytest

from theprotocol.transfer import TransferClient, SmartSendError


def _client_with(handler):
    return TransferClient("https://reg.example", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_send_posts_expected_payload_and_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["idem"] = request.headers.get("idempotency-key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "ok": True, "method": "fx", "status": "completed", "transfer_id": "tx-1",
            "currency_sent": "AVT", "currency_received": "BVT",
        })

    c = _client_with(handler)
    out = await c.send("jwt-123", "did:theprotocol:rx", "2.5",
                       message="memo", backend="async", idempotency_key="k-1")
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/teg/send"
    assert captured["auth"] == "Bearer jwt-123"
    assert captured["idem"] == "k-1"
    assert captured["body"] == {
        "receiver_did": "did:theprotocol:rx", "amount": "2.5",
        "dry_run": False, "message": "memo", "backend": "async",
    }
    assert out["transfer_id"] == "tx-1" and out["method"] == "fx"


@pytest.mark.asyncio
async def test_preview_sets_dry_run_and_omits_optionals():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "method": "local", "status": "dry_run", "dry_run": True})

    c = _client_with(handler)
    out = await c.preview("jwt", "did:theprotocol:rx", "1")
    await c.close()

    assert captured["body"] == {"receiver_did": "did:theprotocol:rx", "amount": "1", "dry_run": True}
    assert out["status"] == "dry_run"


@pytest.mark.asyncio
async def test_non_2xx_raises_smart_send_error_with_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "this frame has FX disabled"})

    c = _client_with(handler)
    with pytest.raises(SmartSendError) as ei:
        await c.send("jwt", "did:theprotocol:rx", "1")
    await c.close()

    assert ei.value.status_code == 409
    assert "FX disabled" in str(ei.value.detail)
