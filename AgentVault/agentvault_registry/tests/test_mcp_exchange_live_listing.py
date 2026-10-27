"""§MCPTEST30 (V0636): the four AGORA read tools name the target's busiest trading listing.

API_TEST_EXCHANGE_LISTING is unset on every sandbox frame since §TESTBED, so the reads asked for the retired tier's TUTCO
and read NOT MEASURED every night while sbx-alpha held five trading listings (one with about 5,000 trades a day,
measured 2026-10-24). The runner now asks the target's own market at bootstrap; a named listing still wins, and no
listing trading keeps the default and its named skip.
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def _answer(listings):
    text = json.dumps({"listings": listings})
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def _run(monkeypatch, *, answer=None, ok=True, raises=False, env=None):
    calls = []

    async def fake_call(target, tool, args, jwt="", timeout=30):
        calls.append((tool, args))
        if raises:
            raise RuntimeError("market unreadable")
        return ok, answer, "200" if ok else "503"

    monkeypatch.setattr(F, "_mcp_rpc_call", fake_call)
    if env is None:
        monkeypatch.delenv("API_TEST_EXCHANGE_LISTING", raising=False)
    else:
        monkeypatch.setenv("API_TEST_EXCHANGE_LISTING", env)
    return asyncio.run(F._live_exchange_listing(object(), "jwt")), calls


def test_the_busiest_trading_listing_is_named(monkeypatch):
    got, calls = _run(monkeypatch, answer=_answer([
        {"symbol": "OLD", "status": "delisted", "stats": {"trades_24h": 99999}},
        {"symbol": "SAW", "status": "trading", "stats": {"trades_24h": 12}},
        {"symbol": "ALFW", "status": "trading", "stats": {"trades_24h": 5164}},
        {"symbol": "HALT", "status": "halted", "stats": {"trades_24h": 40000}},
        {"symbol": "NEW", "status": "trading", "stats": {}},
    ]))
    assert got == "ALFW"
    assert calls == [("theprotocol_getAgoraListings", {})]


def test_a_named_listing_wins_and_the_market_is_not_asked(monkeypatch):
    got, calls = _run(monkeypatch, answer=_answer([{"symbol": "ALFW", "status": "trading"}]), env="TUTCO")
    assert got == "" and calls == []


def test_no_listing_trading_keeps_the_default(monkeypatch):
    got, _ = _run(monkeypatch, answer=_answer([{"symbol": "OLD", "status": "delisted", "stats": {"trades_24h": 7}}]))
    assert got == ""


def test_an_unreadable_market_keeps_the_default(monkeypatch):
    assert _run(monkeypatch, ok=False, answer={"error": {"code": -32000}})[0] == ""
    assert _run(monkeypatch, raises=True)[0] == ""
