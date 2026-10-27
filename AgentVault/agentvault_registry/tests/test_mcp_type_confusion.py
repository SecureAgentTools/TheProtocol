"""§MCPTEST30 (V0524, 2026-10-01) — the type-confusion probe (api_tests/contracts/type_confusion.py): a wrong-typed
argument to every read-only tool must be -32602 or a route's refusal; -32603, a tool-side exception, a 5xx or an
accepted value is the finding (sbx-alpha on V0521: 72 of 107 such calls answered -32603)."""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import type_confusion as TC


def _ro(name):
    return {"readOnlyHint": name.split("_")[-1].startswith(("get", "list"))}


def _schema(name, props, required=()):
    return {"name": name, "inputSchema": {"type": "object", "properties": props, "required": list(required)}}


def test_the_targets():
    public = [
        _schema("theprotocol_getThing", {"thing_id": {"type": "string"}, "limit": {"type": "integer"},
                                         "flag": {"type": ["boolean", "null"]}, "agent_jwt": {"type": "string"}},
                ["thing_id"]),
        _schema("theprotocol_getPlain", {"q": {"type": "string"}}),                 # no typed argument
        _schema("theprotocol_createThing", {"n": {"type": "integer"}}),             # a write
        _schema("theprotocol_getAgentToken", {"n": {"type": "integer"}}),           # left out
    ]
    admin = [_schema("theprotocol_getAdminThing", {"ids": {"type": "array"}, "page": {"type": "integer"}}, ["page"])]
    got = TC.targets(public, admin, {"theprotocol_getThing"}, _ro)
    assert got == [
        ("theprotocol_getThing", "2", {"thing_id": "mcp-probe"}, [("flag", "maybe"), ("limit", "abc")]),
        ("theprotocol_getAdminThing", "admin", {"page": 1}, [("ids", 5), ("page", "abc")]),
    ]


def test_the_answer_kinds():
    assert TC.answer_kind(200, {"error": {"code": -32602, "message": "Invalid params"}}) == "invalid_params"
    assert TC.answer_kind(200, {"error": {"code": -32603, "message": "Internal error"}}) == "jsonrpc_error -32603"
    ok = {"result": {"isError": False, "content": [{"type": "text", "text": "{}"}]}}
    assert TC.answer_kind(200, ok) == "accepted"

    def err(t):
        return {"result": {"isError": True, "content": [{"type": "text", "text": t}]}}
    assert TC.answer_kind(200, err("Error: x returned HTTP 422: limit must be an integer")) == "refused"
    assert TC.answer_kind(200, err("Error: x returned HTTP 500: A database error occurred")) == "server_error"
    assert TC.answer_kind(200, err("Error: TypeError: '>' not supported")) == "tool_crash TypeError"
    assert TC.answer_kind(0, {}) == "no_answer"


def test_the_verdict():
    assert TC.verdict({"limit": "invalid_params", "flag": "refused"})[0] is True
    ok, s, _ = TC.verdict({"limit": "jsonrpc_error -32603", "flag": "invalid_params"})
    assert ok is False and "limit: jsonrpc_error -32603" in s
    assert TC.verdict({"limit": "accepted"})[0] is False
    assert TC.verdict({"limit": "no_answer"})[0] is None


def _outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
    return {"tool": name, "healthy": ok and not skip_reason, "error": fail, "skip_reason": skip_reason}


class _Bag:
    developer_jwt = "dev"
    sentinel_jwt = "agent"


def test_the_run_reads_the_code_through_the_raw_transport():
    sent = []

    async def raw(body, path="/mcp/rpc", jwt="", timeout=30):
        b = json.loads(body)
        sent.append((path, b["params"]["arguments"], jwt))
        return 200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Invalid params: x"}}, ""

    out = {}
    todo = [("theprotocol_getThing", "2", {"thing_id": "mcp-probe"}, [("limit", "abc")]),
            ("theprotocol_getAdminThing", "admin", {}, [("page", "abc")])]
    asyncio.run(TC.run_types(raw, _Bag(), out, _outcome, todo=todo))
    assert sent[0] == ("/mcp/rpc", {"thing_id": "mcp-probe", "agent_jwt": "agent", "limit": "abc"}, "dev")
    assert sent[1] == ("/mcp/admin/rpc", {"page": "abc"}, "dev")
    assert all(r["healthy"] for r in out.values())
    assert "abc" not in json.dumps(out)


def test_no_raw_transport_is_not_measured():
    out = {}
    asyncio.run(TC.run_types(None, _Bag(), out, _outcome, todo=[("theprotocol_getX", "1", {}, [("n", "abc")])]))
    assert out["types: getX"]["skip_reason"].startswith("NOT MEASURED")


def test_the_running_servers_targets():
    got = TC.default_targets()
    names = {t[0] for t in got}
    assert len(got) >= 50 and "theprotocol_discoverAgents" in names and not names & TC.LEFT_OUT
    assert all(typed for _n, _t, _b, typed in got)


def test_the_lifecycle_is_registered_and_its_rows_are_synthetic():
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    assert any(e["name"] == "type_confusion" and e["runner"] is L.lifecycle_type_confusion for e in L.LIFECYCLES)
    assert TC.PREFIX in F._SYNTHETIC_ROW_PREFIXES and "race: " in F._SYNTHETIC_ROW_PREFIXES
