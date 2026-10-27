"""§MCPTEST30 (V0525, 2026-10-01) — the overdraft race (api_tests/contracts/overdraft_race.py): two transfers at once
from a throwaway spender, each 60% of its balance, different keys: one moves, never both. Measured by hand on sbx-alpha
(V0523) first: one moved, one refused "Insufficient balance: have 0.01985, need 0.030150"."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from agentvault_registry.api_tests.contracts import overdraft_race as OR


def _outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
    return {"tool": name, "healthy": ok and not skip_reason, "error": fail, "skip_reason": skip_reason}


def _answered(ok, inner, code):
    return bool(ok)


def _said(inner):
    return (inner or {}).get("_text", "") if isinstance(inner, dict) else str(inner)


class _Bag:
    developer_jwt = "dev"
    sentinel_jwt = "sentinel-jwt"
    sentinel_did = "did:theprotocol:sentinel"


class _Ledger:
    """A spender's balance and ledger; `racy` reads the balance, yields, then debits (the double spend)."""

    def __init__(self, racy=False):
        self.racy = racy
        self.bal = {"did:theprotocol:sentinel": Decimal("100")}
        self.rows = []
        self.deleted = []

    async def rpc(self, tool, args, jwt="", timeout=30):
        await asyncio.sleep(0)
        if tool == "theprotocol_createAgent":
            self.bal["did:theprotocol:spender"] = Decimal("0")
            return True, {"agent_did": "did:theprotocol:spender", "client_id": "c", "client_secret": "s"}, "200"
        if tool == "theprotocol_getAgentToken":
            return True, {"access_token": "spender-jwt"}, "200"
        who = {"sentinel-jwt": "did:theprotocol:sentinel", "spender-jwt": "did:theprotocol:spender"}.get(args.get("agent_jwt"))
        if tool == "theprotocol_getMyBalance":
            return True, {"liquid_balance": str(self.bal[who])}, "200"
        if tool == "theprotocol_getMyTegTransactions":
            return True, {"transactions": [r for r in self.rows if r["from"] == who]}, "200"
        if tool == "theprotocol_deleteMyAgentByDev":
            self.deleted.append(args["agent_did"])
            return True, {}, "200"
        if tool == "theprotocol_transferUnits":
            amt = Decimal(args["amount"])
            need = amt * Decimal("1.005")
            have = self.bal[who]
            if self.racy:
                await asyncio.sleep(0)          # the other request reads the same balance meanwhile
            if have < need:
                return False, {"_text": f"Error: Transfer failed (HTTP 400): Insufficient balance: have {have}, need {need}"}, "400"
            self.bal[who] -= need
            self.bal[args["recipient_did"]] = self.bal.get(args["recipient_did"], Decimal("0")) + amt
            self.rows.append({"from": who, "attached_message": args["message"]})
            return True, {"transaction_id": f"tx{len(self.rows)}"}, "200"
        raise AssertionError(tool)


def test_the_amount_is_sixty_percent_to_the_micro_unit():
    assert OR.race_amount(Decimal("0.05")) == Decimal("0.030000")
    assert OR.race_amount(Decimal("0.0333333")) == Decimal("0.019999")


def test_the_verdict():
    assert OR.verdict(1, 1, Decimal("0.01985"), ["Insufficient balance"]) == (True, None, None)
    ok, fail, _ = OR.verdict(2, 2, Decimal("-0.01"), [])
    assert ok is False and fail.startswith("BUG-FIND: overdraft:") and "below zero" in fail
    assert OR.verdict(1, 2, Decimal("0"), [])[1].startswith("BUG-FIND")          # one answer, two in the ledger
    assert OR.verdict(0, 0, Decimal("0.05"), ["HTTP 403: no permission"])[2].startswith("NOT MEASURED")
    assert OR.verdict(1, None, None, [])[2].startswith("NOT MEASURED")


def test_a_serialized_spender_moves_once_returns_the_rest_and_is_deleted():
    led = _Ledger(racy=False)
    out = {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    r = out[OR.ROW]
    assert r["healthy"] is True, r
    assert r["result_excerpt"]["answered"] == 1 and r["result_excerpt"]["ledger_rows"] == 1
    assert r["result_excerpt"]["refused_for_balance"] == 1 and r["result_excerpt"]["spender_deleted"] is True
    assert led.deleted == ["did:theprotocol:spender"]
    assert led.bal["did:theprotocol:spender"] < Decimal("0.0001")              # what it held went back
    assert "0.03" not in json.dumps(out) and "spender-jwt" not in json.dumps(out)


def test_a_double_spend_is_the_finding():
    led = _Ledger(racy=True)
    out = {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    r = out[OR.ROW]
    assert r["healthy"] is False and r["error"].startswith("BUG-FIND: overdraft:"), r
    assert led.deleted == ["did:theprotocol:spender"]


def test_no_sentinel_or_no_spender_is_not_measured_and_deletes_nothing_it_did_not_make():
    class Bare(_Bag):
        sentinel_jwt = None
    led = _Ledger()
    out = {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, Bare(), out, _outcome, _answered, _said))
    assert out[OR.ROW]["skip_reason"].startswith("NOT MEASURED") and led.deleted == []

    async def refuse(tool, args, jwt="", timeout=30):
        return False, {"_text": "Error: HTTP 403: not allowed"}, "403"
    out = {}
    asyncio.run(OR.run_overdraft(refuse, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    assert out[OR.ROW]["skip_reason"].startswith("NOT MEASURED: no throwaway spender")


def test_the_lifecycle_is_registered_and_its_row_is_synthetic():
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    assert any(e["name"] == "overdraft_race" and e["runner"] is L.lifecycle_overdraft_race for e in L.LIFECYCLES)
    assert OR.PREFIX in F._SYNTHETIC_ROW_PREFIXES


class _LossyLedger(_Ledger):
    """The token call's answer is lost `losses` times (no HTTP status), as on 2026-10-02 04:05Z; or refused."""

    def __init__(self, losses=0, refuse=False):
        super().__init__()
        self.losses, self.refuse, self.token_calls = losses, refuse, 0

    async def rpc(self, tool, args, jwt="", timeout=30):
        if tool == "theprotocol_getAgentToken":
            self.token_calls += 1
            if self.refuse:
                return False, {"_text": "Error: HTTP 403: This agent has been revoked"}, "403"
            if self.token_calls <= self.losses:
                return False, {"_raw": "exec returned no exit code"}, ""
        return await super().rpc(tool, args, jwt=jwt, timeout=timeout)


def test_an_answer_lost_once_is_asked_again_and_the_race_is_measured():
    led = _LossyLedger(losses=1)
    out = {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    r = out[OR.ROW]
    assert r["healthy"] is True, r
    assert led.token_calls == 2 and r["result_excerpt"]["token_attempts"] == 2
    assert led.deleted == ["did:theprotocol:spender"]


def test_an_answer_lost_twice_is_named_as_lost():
    led = _LossyLedger(losses=2)
    out = {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    r = out[OR.ROW]
    assert led.token_calls == 2 and r["skip_reason"].startswith(
        "NOT MEASURED: the throwaway spender's token could not be had (no HTTP status came back, 2 time(s)"), r
    assert led.deleted == ["did:theprotocol:spender"], "the spender it made is deleted either way"


def test_a_refused_token_is_not_asked_twice_and_names_its_status():
    led = _LossyLedger(refuse=True)
    out = {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    r = out[OR.ROW]
    assert led.token_calls == 1, "a refusal is the registry's answer"
    assert r["skip_reason"] == ("NOT MEASURED: the throwaway spender's token could not be had "
                                "(HTTP 403: Error: HTTP 403: This agent has been revoked)"), r


def test_what_counts_as_a_lost_answer():
    assert OR.answer_lost("") and OR.answer_lost(None) and OR.answer_lost("000") and OR.answer_lost("0")
    assert not OR.answer_lost("200") and not OR.answer_lost("403") and not OR.answer_lost(502)


def test_the_funding_sentences_name_what_was_seen():
    # §MCPTEST30 (V0553): round 19 printed "could not be funded" over a transfer that had completed
    assert OR.funding_shortfall(False, "Error: HTTP 400: nope", None, 0).startswith(
        "NOT MEASURED: the spender could not be funded (the transfer answered: Error: HTTP 400")
    assert OR.funding_shortfall(True, "ok", None, 3) == (
        "NOT MEASURED: the funding transfer completed, but the spender's balance could not be read (3 read(s))")
    assert OR.funding_shortfall(True, "ok", Decimal("0"), 3) == (
        "NOT MEASURED: the funding transfer completed, but the spender's balance read 0, 3 time(s)")
    assert OR.funding_shortfall(True, "ok", Decimal("0.05"), 1) is None


class _SlowBalance(_Ledger):
    """The spender's first balance read after its funding fails, as an exec that lost its answer would."""

    def __init__(self, misses):
        super().__init__()
        self.misses, self.spender_reads = misses, 0

    async def rpc(self, tool, args, jwt="", timeout=30):
        if tool == "theprotocol_getMyBalance" and args.get("agent_jwt") == "spender-jwt":
            self.spender_reads += 1
            if self.spender_reads <= self.misses:
                return False, {"_raw": "exec returned no exit code"}, ""
        return await super().rpc(tool, args, jwt=jwt, timeout=timeout)


def test_a_completed_funding_is_read_back_before_it_is_judged(monkeypatch):
    monkeypatch.setattr(OR, "BALANCE_READ_WAIT", 0)
    led, out = _SlowBalance(misses=2), {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    r = out[OR.ROW]
    assert r["healthy"] is True and r["result_excerpt"]["balance_reads"] == 3, r
    led, out = _SlowBalance(misses=3), {}
    asyncio.run(OR.run_overdraft(led.rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    r = out[OR.ROW]
    assert r["skip_reason"] == ("NOT MEASURED: the funding transfer completed, but the spender's balance could not be "
                                "read (3 read(s))"), r
    assert led.deleted == ["did:theprotocol:spender"], "the spender it made is deleted either way"
