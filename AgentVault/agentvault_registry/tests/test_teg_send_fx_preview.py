"""§FESUITE (2026-10-10) — the smart-send dry run previews a cross-frame FX send from the receiver-aware quote.

The console suite's lifecycle 81 (a wallet send from sbx-beta to an agent on sbx-alpha) found Pocket's preview saying
"they receive ≈ 0.9950 SBXB": the sender's currency, for money that arrives as SBXA. The dry run carried no fx_quote,
because its indicative quote read the keyless /fx/rate, which prices only the old AVT/BVT pair (bvt_per_avt or
avt_per_bvt, chosen by whether the sender's currency is "AVT"), and the console fell back to a same-currency reading.
The dry run now asks POST /teg/fx/quote (the Forex desk's receiver-aware quote) with the caller's own token and maps it to
the preview's shape; the old reading stays the fallback. These tests drive `_receiver_fx_quote` with a fake client.
"""
from __future__ import annotations

import pytest

from agentvault_registry.routers import teg_send


class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, response=None, raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.raises:
            raise self.raises
        return self.response


QUOTE = {"same_currency": False, "amount_in": "1", "rate": "0.985", "rate_mode": "pool", "amount_out_gross": "0.985",
         "fee": "0.004925", "amount_out": "0.980075", "fee_pct": "0.500", "slippage": "0", "slippage_max": "0.05",
         "size_cap": "100", "expires_at": "2026-10-10T12:30:00Z"}


@pytest.mark.asyncio
async def test_a_receiver_quote_is_the_preview(monkeypatch):
    client = FakeClient(FakeResponse(200, dict(QUOTE)))
    monkeypatch.setattr(teg_send, "_get_send_client", lambda: client)
    q = await teg_send._receiver_fx_quote("did:theprotocol:sandbox-a.theprotocol.cloud:r1", "1", "agent.jwt")
    assert q == {"rate": "0.985", "est_received": "0.980075", "fee_rate": "0.005", "rate_mode": "pool",
                 "as_of": "2026-10-10T12:30:00Z", "indicative": True}
    assert client.calls[0]["url"].endswith("/api/v1/teg/fx/quote")
    assert client.calls[0]["json"] == {"receiver_did": "did:theprotocol:sandbox-a.theprotocol.cloud:r1", "amount": "1"}
    assert client.calls[0]["headers"] == {"Authorization": "Bearer agent.jwt"}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    FakeResponse(403, {"detail": "fx.quote is required"}),
    FakeResponse(200, dict(QUOTE, same_currency=True)),
    FakeResponse(200, dict(QUOTE, amount_out="")),
    FakeResponse(200, ["not", "a", "quote"]),
])
async def test_no_usable_quote_is_none(monkeypatch, response):
    monkeypatch.setattr(teg_send, "_get_send_client", lambda: FakeClient(response))
    assert await teg_send._receiver_fx_quote("did:theprotocol:x:r1", "1", "agent.jwt") is None


@pytest.mark.asyncio
async def test_no_token_asks_nothing(monkeypatch):
    client = FakeClient(FakeResponse(200, dict(QUOTE)))
    monkeypatch.setattr(teg_send, "_get_send_client", lambda: client)
    assert await teg_send._receiver_fx_quote("did:theprotocol:x:r1", "1", "") is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_a_failing_client_degrades_to_none(monkeypatch):
    monkeypatch.setattr(teg_send, "_get_send_client", lambda: FakeClient(raises=RuntimeError("connection reset")))
    assert await teg_send._receiver_fx_quote("did:theprotocol:x:r1", "1", "agent.jwt") is None
