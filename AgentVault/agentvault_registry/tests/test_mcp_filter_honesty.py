"""§MCPTEST30 (2026-10-01) — the filter honesty probe: a list tool's filter argument is applied, never dropped.

A dropped filter answers 200 with the whole list (CLAUDE.md §DIRFEED), so nothing in the answer says so. The probe asks
each read-only list tool once without its filter (the control must return rows) and once per filter with a nonce that
matches nothing: no rows or a refusal is right, rows are the finding.
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import filter_honesty as FH


def _schema(name, props, required=()):
    return {"name": name, "inputSchema": {"type": "object", "properties": props, "required": list(required)}}


S = {"type": "string"}


def test_targets_take_optional_string_filters_of_read_only_tools():
    public = [
        _schema("theprotocol_listThings", {"agent_did": S, "status": S, "sort_by": S, "limit": {"type": "integer"},
                                           "kind": {"type": "string", "enum": ["a", "b"]}}),
        _schema("theprotocol_getThing", {"thing_id": S, "agent_did": S}, required=("thing_id", "agent_did")),
        _schema("theprotocol_writeThing", {"status": S}),
    ]
    admin = [_schema("theprotocol_adminList", {"event_type": S})]
    ro = {"theprotocol_listThings": True, "theprotocol_getThing": True, "theprotocol_writeThing": False,
          "theprotocol_adminList": True}
    got = FH.targets(public, admin, {"theprotocol_listThings"}, lambda n: {"readOnlyHint": ro[n]})
    assert got == [("theprotocol_listThings", "2", {}, ["agent_did", "status"]),
                   ("theprotocol_adminList", "admin", {}, ["event_type"])], got


def test_a_did_filter_gets_a_did_shaped_nonce():
    assert FH.nonce_for("agent_did").startswith("did:theprotocol:")
    assert FH.nonce_for("status").startswith("zz-mcp-filter-") and FH.nonce_for("status") != FH.nonce_for("status")


def _env(data=None, is_error=False):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(data)}], "isError": is_error}}


def test_read():
    assert FH.read(_env({"items": [{"id": 1}, {"id": 2}]})) == ("rows", 2)
    assert FH.read(_env([])) == ("rows", 0)
    assert FH.read(_env({"error": "no such listing"})) == ("refused", None)
    assert FH.read({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602}}) == ("refused", None)
    assert FH.read({}) == ("no_answer", None)


def test_verdict():
    assert FH.verdict(("rows", 5), {"status": ("rows", 0), "agent_did": ("refused", None)})[0] is True
    healthy, sentence, _ev = FH.verdict(("rows", 5), {"status": ("rows", 5), "agent_did": ("rows", 0)})
    assert healthy is False and "status" in sentence and "agent_did" not in sentence.split("for ")[1].split(":")[0]
    assert FH.verdict(("rows", 0), {"status": ("rows", 0)})[0] is None, "an empty list cannot show a dropped filter"
    assert FH.verdict(("no_answer", None), {"status": ("rows", 3)})[0] is None


class _Registry:
    def __init__(self, honours: bool):
        self.honours = honours

    async def raw(self, body, path="/mcp/rpc", jwt="", timeout=30):
        args = json.loads(body)["params"]["arguments"]
        filtered = any(k != "agent_jwt" for k in args)
        rows = [] if (filtered and self.honours) else [{"id": 1}, {"id": 2}, {"id": 3}]
        return "200", _env({"items": rows}), None


def _run(registry):
    out = {}

    def make_outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"healthy": ok, "fail_reason": fail, "skip_reason": skip_reason}

    bag = type("Bag", (), {"developer_jwt": "dev.jwt", "sentinel_jwt": "agent.jwt"})()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(FH.run_filters(registry.raw, bag, out, make_outcome,
                                               todo=[("theprotocol_listThings", "2", {}, ["agent_did", "status"])]))
    finally:
        loop.close()
    return out[FH.PREFIX + "listThings"]


def test_an_honest_registry_passes_and_a_dropped_filter_is_named():
    assert _run(_Registry(honours=True))["healthy"] is True
    row = _run(_Registry(honours=False))
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND: filter") and "agent_did" in row["fail_reason"]
