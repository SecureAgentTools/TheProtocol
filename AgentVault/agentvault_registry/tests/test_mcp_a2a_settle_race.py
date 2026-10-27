"""§MCPTEST30 (2026-10-01) — the A2A settle race probe: one payment token pays at most once.

The verdicts on their own, then the probe driven against a fake registry that plays the A2A rail: once with settle's
compare-and-set claim (one settle wins, the other is refused 409; a release racing a settle loses or wins cleanly), and
once without it (both settles fire a transfer). The honest registry passes both rows; the one without the claim is named.
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import a2a_settle_race as AR


def test_the_settlement_marker_and_the_row_count():
    assert AR.settlement_marker("0123456789abcdef") == "token=01234567"
    txs = [{"attached_message": "A2A service payment (token=01234567, task=n/a)"},
           {"attached_message": "something else"}, {"attached_message": None}, "junk"]
    assert AR.rows_for(txs, "0123456789abcdef") == 1
    assert AR.rows_for(None, "0123456789abcdef") is None


def test_twice_verdict():
    assert AR.twice_verdict("settled", 1) == (True, None, None)
    healthy, fail, _ = AR.twice_verdict("settled", 2)
    assert healthy is False and fail.startswith("BUG-FIND: a2a_race") and "2 times" in fail
    assert AR.twice_verdict("failed", 0)[0] is None
    assert AR.twice_verdict("settled", 0)[0] is None, "a settled token with no row yet is a lag, not a finding"
    assert AR.twice_verdict(None, 1)[0] is None


def test_release_verdict():
    assert AR.release_verdict("settled", 1) == (True, None, None)
    assert AR.release_verdict("released", 0) == (True, None, None)
    healthy, fail, _ = AR.release_verdict("released", 1)
    assert healthy is False and "BOTH took effect" in fail
    assert AR.release_verdict("settled", 2)[0] is False
    assert AR.release_verdict("failed", 0)[0] is None


def _env(inner):
    return {"result": {"content": [{"type": "text", "text": json.dumps(inner)}]}}


class _Rail:
    """A fake registry for the run: agents, a sentinel, A2A tokens, and the payer's ledger."""

    def __init__(self, claim: bool):
        self.claim = claim
        self.tokens = {}
        self.ledger = []
        self.deleted = []
        self.n = 0

    async def rpc(self, tool, args, jwt="", timeout=30):
        if tool == "theprotocol_createAgent":
            return True, _env({"did": "did:payer", "client_id": "c", "client_secret": "s"}), "200"
        if tool == "theprotocol_getAgentToken":
            return True, _env({"access_token": "payer.jwt"}), "200"
        if tool == "theprotocol_transferUnits":
            return True, _env({"status": "completed"}), "200"
        if tool == "theprotocol_authorizePayment":
            self.n += 1
            tid = f"{self.n:08d}deadbeef"
            self.tokens[f"apt_{self.n}"] = {"id": tid, "status": "authorized"}
            return True, _env({"token": f"apt_{self.n}", "token_id": tid}), "200"
        if tool == "theprotocol_verifyPayment":
            self.tokens[args["token"]]["status"] = "consumed"
            return True, _env({"valid": True, "status": "consumed"}), "200"
        if tool == "theprotocol_settlePayment":
            t = self.tokens[args["token"]]
            if t["status"] not in ("consumed", "authorized"):
                return True, _env({"error": f"HTTP 409: Cannot settle token in status: {t['status']}"}), "409"
            if self.claim:
                t["status"] = "settling"      # the claim: the check and the write are ONE step (the route's UPDATE)
            await asyncio.sleep(0)            # the transfer runs later; without the claim both racers got past the check
            t["status"] = "settled"
            self.ledger.append({"attached_message": f"A2A service payment (token={t['id'][:8]}, task=n/a)"})
            return True, _env({"status": "settling", "token_id": t["id"]}), "200"
        if tool == "theprotocol_releasePayment":
            t = self.tokens[args["token"]]
            if t["status"] in ("consumed", "authorized"):
                t["status"] = "released"
                return True, _env({"status": "released"}), "200"
            return True, _env({"error": f"HTTP 409: Cannot release token in status: {t['status']}"}), "409"
        if tool == "theprotocol_getMyPaymentAuthorizations":
            return True, _env({"tokens": [{"token_id": t["id"], "status": t["status"]} for t in self.tokens.values()]}), "200"
        if tool == "theprotocol_getMyTegTransactions":
            return True, _env({"transactions": list(self.ledger)}), "200"
        if tool == "theprotocol_getMyBalance":
            return True, _env({"liquid_balance": "0.02"}), "200"
        if tool == "theprotocol_deleteMyAgentByDev":
            self.deleted.append(args["agent_did"])
            return True, _env({}), "204"
        raise AssertionError(tool)


def _run(rail):
    out = {}
    bag = type("Bag", (), {"developer_jwt": "dev.jwt", "sentinel_jwt": "sentinel.jwt", "sentinel_did": "did:sentinel"})()

    def parse(body):
        return json.loads(body["result"]["content"][0]["text"])

    def answered(ok, inner, code):
        return bool(ok) and str(code).startswith("2") and not (isinstance(inner, dict) and inner.get("error"))

    def make_outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"healthy": ok, "fail_reason": fail, "skip_reason": skip_reason}

    async def no_sleep(_s):
        return None

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(AR.run_a2a_race(rail.rpc, parse, bag, out, make_outcome, answered,
                                                lambda inner: json.dumps(inner)[:80], sleep=no_sleep))
    finally:
        loop.close()
    return out


def test_a_registry_with_the_settle_claim_passes_both_rows_and_the_payer_is_deleted():
    rail = _Rail(claim=True)
    out = _run(rail)
    assert out[AR.ROW_TWICE]["healthy"] is True, out[AR.ROW_TWICE]
    assert out[AR.ROW_TWICE]["result_excerpt"]["ledger_rows"] == 1
    assert out[AR.ROW_RELEASE]["healthy"] is True, out[AR.ROW_RELEASE]
    assert rail.deleted == ["did:payer"]


def test_a_registry_without_the_claim_pays_twice_and_is_named():
    out = _run(_Rail(claim=False))
    row = out[AR.ROW_TWICE]
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND") and "2 times" in row["fail_reason"]


def test_no_credential_reaches_a_row():
    assert "jwt" not in json.dumps(_run(_Rail(claim=True)))


class _RefusingRail(_Rail):
    """authorize refuses (what V0526 answers a valid caller when its database is full)."""

    async def rpc(self, tool, args, jwt="", timeout=30):
        if tool == "theprotocol_authorizePayment":
            return False, _env({"error": "This tool requires agent authentication."}), "401"
        return await super().rpc(tool, args, jwt, timeout)


def test_a_refused_setup_is_not_measured_and_says_which_step_and_why():
    out = _run(_RefusingRail(claim=True))
    for name in (AR.ROW_TWICE, AR.ROW_RELEASE):
        skip = out[name]["skip_reason"]
        assert out[name]["fail_reason"] is None and skip.startswith("NOT MEASURED")
        assert "authorize refused" in skip and "requires agent authentication" in skip, skip
