"""§MCPTEST30 (2026-10-01) — bounds the MCP tester asks for: a page of 0, of -1, from offset -1 and of 5000 on every paged
tool, and amounts no ledger can hold on transferUnits.

Postgres refuses a negative LIMIT or OFFSET with an error, so a route that hands the bound to its SQL unchecked answers
500 where it should refuse or clamp; the transfer route takes its amount as a string into its spend gate, its fee
arithmetic and the TEG, where NaN raises on the first comparison. A server error is the finding, and so is an accepted
impossible amount; a refusal or a clamp is the right answer.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts import pagination_partition as PP
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (
    _SYNTHETIC_ROW_PREFIXES, _parse_rpc_result)


def _ok(payload):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}, "200"


def _err(text):
    return False, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}, "200"


def _kind(answer):
    ok, body, code = answer
    return PP.bound_answer(ok, _parse_rpc_result(body), code, L._answered)


def test_a_bounds_answer_is_rows_a_refusal_a_server_error_or_nothing():
    assert _kind(_ok({"items": [{"id": 1}, {"id": 2}]})) == ("rows", None, 2)
    assert _kind(_err("Error: getMyIncome refused (HTTP 422): limit must be at least 1")) == ("refused", 422, None)
    assert _kind(_err("Error: getAdminAgents returned HTTP 500")) == ("server_error", 500, None)
    assert _kind(_err("Error: Internal Server Error")) == ("server_error", None, None)
    assert _kind((False, {}, "502")) == ("no_answer", None, None)


def test_a_wrapped_refusal_is_classified_by_its_status_never_lost():
    """Round 7: the sweep's transport returns a tool's own refusal with the wrapped status as the code; NaN answered a
    wrapped 500 and the judge called it `no_answer`, hiding the crash."""
    def _wrapped(code, text):
        return False, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}, code
    assert _kind(_wrapped("500", "Error: Transfer failed (HTTP 500): Internal Server Error")) == ("server_error", 500, None)
    assert _kind(_wrapped("422", "Error: Transfer failed (HTTP 422): Amount must be positive")) == ("refused", 422, None)
    assert _kind(_ok({"status_code": 404, "upstream_error": "x returned HTTP 404"})) == ("refused", 404, None)
    assert _kind((False, {}, "")) == ("no_answer", None, None)


def test_only_a_server_error_fails_and_an_uncapped_page_is_recorded():
    rows, refused, boom = ("rows", None, 3), ("refused", 422, None), ("server_error", 500, None)
    healthy, sentence, ev = PP.bounds_verdict({"limit=0": refused, "limit=-1": refused, "offset=-1": rows,
                                               "limit=5000": ("rows", None, 4200)})
    assert healthy is True and sentence is None and ev["uncapped"] is True and ev["limit=0"] == "refused HTTP 422"
    healthy, sentence, ev = PP.bounds_verdict({"limit=0": rows, "limit=-1": boom, "offset=-1": boom, "limit=5000": rows})
    assert healthy is False and sentence.startswith("BUG-FIND: bounds:") and "limit=-1, offset=-1" in sentence
    healthy, sentence, _ = PP.bounds_verdict({c: ("no_answer", None, None) for c, _p in PP.BOUND_CASES})
    assert healthy is None and sentence.startswith("NOT MEASURED")


class _Bag:
    developer_jwt, sentinel_jwt, sentinel_did = "dev", "sentinel-jwt", "did:theprotocol:sentinel"

    def __init__(self, second=True):
        self.values = {"second_agent_did": "did:theprotocol:second"} if second else {}

    def get(self, k, d=None):
        return self.values.get(k, d)


def test_run_bounds_asks_four_bounds_per_tool_and_judges_them():
    seen = []

    async def rpc(tool, args, jwt="", timeout=30):
        seen.append((tool, args["limit"], args["offset"]))
        if args["limit"] < 0 or args["offset"] < 0:
            return _err(f"Error: {tool} returned HTTP 500")
        return _ok({"items": [{"id": i} for i in range(min(args["limit"], 2))]})
    out = {}
    asyncio.run(PP.run_bounds(rpc, _parse_rpc_result, _Bag(), out, (("theprotocol_getMyIncome", "2", {}),),
                              L._make_outcome, L._answered))
    row = out["bounds: getMyIncome"]
    assert [s[1:] for s in seen] == [(0, 0), (-1, 0), (PP.PAGE, -1), (5000, 0)]
    assert row["healthy"] is False and "limit=-1, offset=-1" in row["fail_reason"]
    assert row["probe_expect_status"] == "any" and row["result_excerpt"]["limit=5000"] == "2 rows"
    assert any("bounds: ".startswith(p) or p == "bounds: " for p in _SYNTHETIC_ROW_PREFIXES)


def _amounts(answer_for, second=True):
    out = {}

    async def rpc(tool, args, jwt="", timeout=30):
        if tool != "theprotocol_transferUnits":
            assert args.get("amount") == "NaN" and args.get("agent_jwt") == "sentinel-jwt"
            if "${receiver}" in json.dumps(args):
                raise AssertionError("the receiver placeholder must be filled")
            return answer_for("NaN")
        assert args["recipient_did"] == "did:theprotocol:second"
        return answer_for(args["amount"])
    asyncio.run(L.lifecycle_amount_bounds(rpc, _parse_rpc_result, _Bag(second), out))
    return out


def test_impossible_amounts_must_be_refused_and_none_may_answer_a_server_error():
    def refuse_impossible(amount):
        if amount in ("-0.01", "0", "NaN", "Infinity"):
            return _err(f"Error: Transfer failed (HTTP 422): amount {amount} must be a positive finite decimal")
        return _ok({"transaction_id": "tx-1", "status": "completed"})
    out = _amounts(refuse_impossible)
    assert set(out) == ({f"amount: transferUnits {a}" for a, _w, _m in L.AMOUNT_CASES}
                        | {f"amount: {t.replace('theprotocol_', '')} NaN" for t, _a in L.NAN_TOOLS})
    assert all(r["healthy"] for r in out.values()), {k: r["fail_reason"] for k, r in out.items()}
    assert out["amount: transferUnits NaN"]["probe_expect_status"] == "error_4xx"
    assert out["amount: transferUnits 1e-2"]["probe_expect_status"] == "any"

    def accept_all(amount):
        return _ok({"transaction_id": "tx-1"}) if amount != "NaN" else _err("Error: Transfer failed (HTTP 500): boom")
    out = _amounts(accept_all)
    assert out["amount: transferUnits -0.01"]["fail_reason"] == ("BUG-FIND: amount: transferUnits ACCEPTED a "
                                                                  "negative amount (-0.01)")
    assert out["amount: transferUnits NaN"]["fail_reason"].startswith("BUG-FIND: amount: transferUnits answered a "
                                                                       "server error for not a number")
    assert out["amount: transferUnits 1e-2"]["healthy"] is True, "0.01 in scientific notation may be moved"
    skipped = _amounts(refuse_impossible, second=False)
    assert all(r["skip_reason"].startswith("NOT MEASURED") for r in skipped.values())


def test_the_bounds_lifecycles_are_registered():
    names = [lc["name"] for lc in L.LIFECYCLES]
    assert "page_bounds" in names and "amount_bounds" in names
    assert names.index("page_bounds") == names.index("pagination_partition") + 1
    assert names.index("amount_bounds") == names.index("money_idempotent_replay") + 1
    assert "amount: " in _SYNTHETIC_ROW_PREFIXES and "bounds: " in _SYNTHETIC_ROW_PREFIXES


class _Resp:
    status_code, text = 404, '{"detail": "Dispute not found"}'
    headers = {"content-type": "application/json"}

    def json(self):
        return {"detail": "Dispute not found"}


class _Client:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None, **k):
        return _Resp()


def test_a_dispute_detail_refusal_carries_the_routes_reason(monkeypatch):
    from agentvault_registry.mcp import tools_agent, tools_developer

    class _Auth:
        raw_token, agent_did, auth_type = "agent-jwt", "did:theprotocol:a", "agent"
    monkeypatch.setattr(tools_agent.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(tools_agent, "require_agent_auth", lambda auth: None)
    out = asyncio.run(tools_developer.get_teg_dispute_detail(_Auth(), dispute_log_id="0000"))
    assert out == {"error": "getTegDisputeDetail refused (HTTP 404): Dispute not found"}
    plain = asyncio.run(tools_agent._agent_get(_Auth(), "/api/v1/x", op_name="x"))
    # V0514: the default refusal keeps its text and carries the route's reason too (mcp/refusal.http_refusal)
    assert plain["error"] == "x returned HTTP 404: Dispute not found"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
