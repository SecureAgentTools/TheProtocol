"""§MCPTEST30 (V0525, 2026-10-01) — the value-range probe (api_tests/contracts/value_range.py): values a JSON type carries
but the database cannot (2^31, 2^63, 1e308, dates that are none), asked of every read-only tool. Measured by hand on
sbx-alpha (V0521) first: getProposalDetail 500 with the driver's words, /teg/transactions offset=2^63 as a TEG 503."""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import value_range as VR

SCHEMAS = [
    {"name": "theprotocol_getProposalDetail", "inputSchema": {"type": "object", "required": ["proposal_id"], "properties": {
        "proposal_id": {"type": "integer"}}}},
    {"name": "theprotocol_getMyTegTransactions", "inputSchema": {"type": "object", "properties": {
        "limit": {"type": "integer"}, "offset": {"type": "integer"}, "agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_getThings", "inputSchema": {"type": "object", "required": ["org_id"], "properties": {
        "org_id": {"type": "string"}, "since": {"type": "string"}, "kind": {"type": "string", "enum": ["a", "b"]},
        "min_score": {"type": "number"}, "note": {"type": "string"}}}},
    {"name": "theprotocol_deleteThing", "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    {"name": "theprotocol_getAgentToken", "inputSchema": {"type": "object", "properties": {"n": {"type": "integer"}}}},
]


def _annotate(name):
    return {"readOnlyHint": not name.startswith("theprotocol_delete")}


def test_the_values_each_argument_is_asked_with():
    assert [l for l, _ in VR.values_for("proposal_id", {"type": "integer"})] == ["int32+1", "int64+1"]
    assert [l for l, _ in VR.values_for("limit", {"type": ["integer", "null"]})] == ["int64+1"]   # a page size: no 2^31
    assert [l for l, _ in VR.values_for("min_score", {"type": "number"})] == ["1e308"]
    assert [l for l, _ in VR.values_for("since", {"type": "string"})] == ["not-a-date", "feb30", "year99999"]
    assert [l for l, _ in VR.values_for("valid_until", {"type": "string", "format": "date-time"})][:1] == ["not-a-date"]
    assert VR.values_for("kind", {"type": "string", "enum": ["a"]}) == () and VR.values_for("note", {"type": "string"}) == ()
    assert dict(VR.INT_VALUES)["int64+1"] == 2 ** 63 and dict(VR.INT_VALUES)["int32+1"] == 2 ** 31


def test_targets_are_the_read_only_tools_with_a_measurable_argument():
    got = {t[0]: t for t in VR.targets(SCHEMAS, [], {"theprotocol_getMyTegTransactions"}, _annotate)}
    assert set(got) == {"theprotocol_getProposalDetail", "theprotocol_getMyTegTransactions", "theprotocol_getThings"}
    assert got["theprotocol_getMyTegTransactions"][1] == "2"
    assert [(p, l) for p, l, _ in got["theprotocol_getMyTegTransactions"][3]] == [
        ("limit", "int64+1"), ("offset", "int32+1"), ("offset", "int64+1")]          # agent_jwt is never set
    tool, tier, base, cases = got["theprotocol_getThings"]
    assert tier == "1" and base == {"org_id": "mcp-probe"}
    assert [(p, l) for p, l, _ in cases] == [("min_score", "1e308"), ("since", "not-a-date"), ("since", "feb30"),
                                             ("since", "year99999")]


def _res(text, err=True):
    return {"jsonrpc": "2.0", "id": 1, "result": {"isError": err, "content": [{"type": "text", "text": text}]}}


def test_the_kinds():
    assert VR.answer_kind("200", {"error": {"code": -32602, "message": "Invalid params"}}) == "invalid_params"
    assert VR.answer_kind("200", {"error": {"code": -32603, "message": "Internal error"}}) == "jsonrpc_error -32603"
    assert VR.answer_kind("200", _res("Error: HTTP 422: A path or query parameter value is out of range")) == "refused"
    assert VR.answer_kind("200", _res("Error: getMyTegTransactions returned HTTP 503: Unable to fetch")) == "server_error 503"
    assert VR.answer_kind("200", _res("Error: HTTP 500: Failed to retrieve proposal: (sqlalchemy.dialects.postgresql."
                                      "asyncpg.Error) invalid input for query argument $1: 2147483648")) == "db_words"
    assert VR.answer_kind("200", _res('{"items": [], "error": "[SQL: SELECT 1]"}', err=False)) == "db_words"
    assert VR.answer_kind("200", _res('{"items": []}', err=False)) == "answered"
    assert VR.answer_kind("200", _res("Error: OverflowError: date value out of range")) == "tool_crash OverflowError"
    assert VR.answer_kind("0", None) == "no_answer"


def test_the_verdict():
    ok, s, ev = VR.verdict({"proposal_id=int32+1": "db_words", "proposal_id=int64+1": "server_error 500"})
    assert ok is False and s.startswith("BUG-FIND: range:") and "proposal_id=int32+1: db_words" in s
    assert VR.verdict({"a=x": "refused", "b=y": "answered", "c=z": "invalid_params"})[0] is True
    assert VR.verdict({"a=x": "no_answer"})[0] is None


def test_the_run_asks_each_case_once_through_the_raw_transport_and_keeps_no_value():
    calls = []

    async def raw(body, path="/mcp/rpc", jwt="", timeout=30):
        await asyncio.sleep(0)
        b = json.loads(body)
        calls.append((path, b["params"]["name"], b["params"]["arguments"]))
        args = b["params"]["arguments"]
        if args.get("proposal_id", 0) > 2 ** 31 - 1:
            return "200", _res("Error: HTTP 422: A path or query parameter value is out of range or invalid."), ""
        return "200", _res('{"items": []}', err=False), ""

    def make(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"tool": name, "healthy": ok, "error": fail, "skip_reason": skip_reason}

    class Bag:
        developer_jwt = "dev"
        sentinel_jwt = "agent"

    out = {}
    todo = VR.targets(SCHEMAS, [], {"theprotocol_getMyTegTransactions"}, _annotate)
    asyncio.run(VR.run_range(raw, Bag(), out, make, todo))
    assert sorted(out) == ["range: getMyTegTransactions", "range: getProposalDetail", "range: getThings"]
    assert all(r["healthy"] for r in out.values()), out
    assert len(calls) == 2 + 3 + 4
    assert all(a.get("agent_jwt") == "agent" for _p, n, a in calls if n == "theprotocol_getMyTegTransactions")
    assert "9223372036854775808" not in json.dumps(out) and "2147483648" not in json.dumps(out)   # labels, never values


def test_no_transport_or_no_agent_is_not_measured():
    def make(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"tool": name, "healthy": ok, "error": fail, "skip_reason": skip_reason}

    class Bag:
        developer_jwt = "dev"
        sentinel_jwt = None

    out = {}
    asyncio.run(VR.run_range(None, Bag(), out, make, VR.targets(SCHEMAS[:1], [], set(), _annotate)))
    assert out["range: getProposalDetail"]["skip_reason"].startswith("NOT MEASURED")
    out = {}

    async def raw(*_a, **_k):
        raise AssertionError("a tier-2 tool without the sentinel's token must not be called")
    asyncio.run(VR.run_range(raw, Bag(), out, make, VR.targets(SCHEMAS[1:2], [], {"theprotocol_getMyTegTransactions"}, _annotate)))
    assert out["range: getMyTegTransactions"]["skip_reason"] == "NOT MEASURED: no sentinel agent token"


def test_the_real_catalog_and_the_registration():
    todo = {t[0]: t for t in VR.default_targets()}
    assert len(todo) >= 60, len(todo)        # 76 read-only tools on sbx-alpha's V0521 catalog
    assert any(p == "proposal_id" for p, _l, _v in todo["theprotocol_getProposalDetail"][3])
    assert ("offset", "int64+1") in {(p, l) for p, l, _v in todo["theprotocol_getMyTegTransactions"][3]}
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    assert any(e["name"] == "value_range" and e["runner"] is L.lifecycle_value_range for e in L.LIFECYCLES)
    assert VR.PREFIX in F._SYNTHETIC_ROW_PREFIXES
