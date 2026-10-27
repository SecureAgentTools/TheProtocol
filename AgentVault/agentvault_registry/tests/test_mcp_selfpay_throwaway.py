"""§MCPTEST30 (V0585): the self-payment balance check pays from a throwaway agent, never the sentinel.

Lifecycles run six at once and several pay the run's sentinel while this check waits: the A2A settle race returns its
payer's dust to it, which read "+0.028476" as a BUG-FIND here on sbx-alpha (2026-10-05) and on the nightly pair nt261008
(2026-10-08), the same amount both times and no settle in it. A throwaway nobody else pays makes any rise the settle's.
Driven over a fake transport (test_mcp_mtls_toggle_verifies.py's shape).
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L

PAYER = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-0000self0pay1"


def _drive(monkeypatch, before="0.05", after="0.05", token_ok=True):
    calls = []

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(L.asyncio, "sleep", no_sleep)

    def body(obj):
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                       "structuredContent": obj}}
    balances = iter([before, after])

    async def rpc(tool, args, jwt="", timeout=15):
        calls.append((tool, dict(args)))
        if tool == "theprotocol_createAgent":
            return True, body({"agent_did": PAYER, "client_id": "cid", "client_secret": "csec"}), "201"
        if tool == "theprotocol_getAgentToken":
            return (True, body({"access_token": "payer-jwt"}), "200") if token_ok else (False, body({"error": "no"}), "401")
        if tool == "theprotocol_getMyBalance":
            return True, body({"liquid_balance": next(balances), "staked_balance": "0"}), "200"
        if tool == "theprotocol_authorizePayment":
            return True, body({"token": "apt_x", "token_id": "t1"}), "201"
        return True, body({"status": "ok"}), "200"

    def parse(b):
        try:
            return json.loads(b["result"]["content"][0]["text"])
        except Exception:
            return {}

    class Bag:
        developer_jwt, sentinel_jwt = "dev", "sentinel-jwt"
        sentinel_did = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-00000sentinel"
    out = {"theprotocol_settlePayment": {"healthy": True, "fail_reason": None}}   # the settle row another lifecycle wrote
    asyncio.run(L.lifecycle_a2a_payment_settle_balance(rpc, parse, Bag(), out))
    return out, calls


def test_a_rise_on_the_throwaway_is_the_finding(monkeypatch):
    out, _ = _drive(monkeypatch, before="0.0497", after="0.0597")
    row = out["theprotocol_settlePayment"]
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND: settlePayment (self-pay)")


def test_an_unmoved_or_lower_balance_passes(monkeypatch):
    for after in ("0.0497", "0.0496"):
        out, _ = _drive(monkeypatch, before="0.0497", after=after)
        assert out["theprotocol_settlePayment"]["healthy"] is True


def test_the_sentinel_only_funds_and_receives(monkeypatch):
    _out, calls = _drive(monkeypatch, before="0.0497", after="0.0497")
    tools = [t for t, _a in calls]
    assert tools == ["theprotocol_createAgent", "theprotocol_getAgentToken", "theprotocol_transferUnits",
                     "theprotocol_getMyBalance", "theprotocol_authorizePayment", "theprotocol_settlePayment",
                     "theprotocol_getMyBalance", "theprotocol_transferUnits", "theprotocol_deleteMyAgentByDev"]
    by = dict(calls[:3])
    assert by["theprotocol_transferUnits"]["agent_jwt"] == "sentinel-jwt" and by["theprotocol_transferUnits"]["recipient_did"] == PAYER
    for tool, args in calls:
        if tool in ("theprotocol_getMyBalance", "theprotocol_authorizePayment", "theprotocol_settlePayment"):
            assert args["agent_jwt"] == "payer-jwt", tool          # never the sentinel's balance, never its payment
    assert [a for t, a in calls if t == "theprotocol_authorizePayment"][0]["target_agent_did"] == PAYER
    back = [a for t, a in calls if t == "theprotocol_transferUnits"][1]
    assert back["agent_jwt"] == "payer-jwt" and back["recipient_did"].endswith("00000sentinel")


def test_the_throwaway_is_deleted_even_when_its_token_is_not_had(monkeypatch):
    _out, calls = _drive(monkeypatch, token_ok=False)
    assert [t for t, _a in calls][-1] == "theprotocol_deleteMyAgentByDev"
    assert calls[-1][1] == {"agent_did": PAYER}
