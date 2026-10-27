"""§MCPTEST30 (2026-10-01) — the enum filter probe: every value a tool's enum filter advertises is one its route applies.

Its three findings are the three shapes measured on sbx-alpha (V0526): a value the route refuses as invalid
(getRecentWebhookDeliveries `failure`), a value answered with other values (getInviteCodes `revoked`: every row active),
and a value that matches nothing though the data holds it (getMyPaymentAuthorizations `SETTLED` vs the column's `settled`).
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import enum_filter as EF


def _schema(name, props, required=()):
    return {"name": name, "inputSchema": {"type": "object", "properties": props, "required": list(required)}}


def test_targets_take_optional_enum_filters_and_skip_modes():
    public = [
        _schema("theprotocol_listThings", {"status": {"type": "string", "enum": ["open", "closed", "all"]},
                                           "tf": {"type": "string", "enum": ["1m", "1h"]},
                                           "role": {"type": "string", "enum": ["client", "provider"]}}),
        _schema("theprotocol_getThing", {"status": {"type": "string", "enum": ["a"]}}, required=("status",)),
        _schema("theprotocol_writeThing", {"status": {"type": "string", "enum": ["a"]}}),
    ]
    admin = [_schema("theprotocol_adminList", {"status_filter": {"type": "string", "enum": ["active", "used"]}})]
    ro = {"theprotocol_listThings": True, "theprotocol_getThing": True, "theprotocol_writeThing": False,
          "theprotocol_adminList": True}
    got = EF.targets(public, admin, set(), lambda n: {"readOnlyHint": ro[n]})
    assert got == [("theprotocol_listThings", "1", {}, "status", ["open", "closed"]),
                   ("theprotocol_adminList", "admin", {}, "status_filter", ["active", "used"])], got
    assert EF.field_for("status_filter") == "status" and EF.field_for("severity") == "severity"


def _env(data, is_error=False):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(data)}], "isError": is_error}}


def test_read():
    assert EF.read(_env({"items": [{"status": "a"}]}))[0:2] == ("rows", [{"status": "a"}])
    kind, rows, text = EF.read(_env({"status_code": 400, "upstream_error": "Invalid status: failure"}))
    assert kind == "refused" and "Invalid status: failure" in text
    assert EF.read({"jsonrpc": "2.0", "id": 1, "error": {"code": -32003, "message": "busy"}})[0] == "unavailable"
    assert EF.read({})[0] == "no_answer"


def rows(*values, field="status"):
    return ("rows", [{field: v} for v in values], "")


def test_the_three_measured_shapes_are_findings():
    # refused: the route does not know its own advertised value
    h, s, _ = EF.verdict("status", rows("success", "pending"),
                         {"success": rows("success"), "failure": ("refused", None, "HTTP 400: Invalid status: failure")})
    assert h is False and "refused its own advertised value failure" in s
    # dropped: asked for revoked, every row is active
    h, s, _ = EF.verdict("status_filter", rows("active", "active"),
                         {"active": rows("active"), "revoked": rows("active", "active")})
    assert h is False and "answered other values for revoked" in s
    # unmatched: the data holds settled, asking SETTLED returns nothing
    h, s, _ = EF.verdict("status", rows("settled", "released"), {"SETTLED": rows(), "RELEASED": rows()})
    assert h is False and "matched nothing for SETTLED, RELEASED" in s, "in the order the values were asked"


def test_a_vocabulary_the_route_speaks_passes():
    h, s, ev = EF.verdict("status", rows("settled", "released"),
                          {"SETTLED": rows("settled"), "RELEASED": rows("released"), "FAILED": rows()})
    assert h is True and s is None and ev["FAILED"] == "0 rows"


def test_a_busy_registry_or_an_unread_control_measures_nothing():
    assert EF.verdict("status", ("no_answer", None, ""), {"a": ("unavailable", None, "")})[0] is None
    # a refusal that is not about the value (a 403) is not a finding
    assert EF.verdict("status", rows("a"), {"a": rows("a"), "b": ("refused", None, "HTTP 403: admin required")})[0] is True


class _Registry:
    def __init__(self, drops: bool):
        self.drops = drops

    async def raw(self, body, path="/mcp/rpc", jwt="", timeout=30):
        args = json.loads(body)["params"]["arguments"]
        data = [{"status": "active"}, {"status": "used"}]
        v = args.get("status_filter")
        if v and not self.drops:
            data = [r for r in data if r["status"] == v]
        return "200", _env({"invite_codes": data}), None


def _run(registry):
    out = {}

    def make_outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"healthy": ok, "fail_reason": fail, "skip_reason": skip_reason}

    bag = type("Bag", (), {"developer_jwt": "dev.jwt"})()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(EF.run_enums(registry.raw, bag, out, make_outcome,
                                             todo=[("theprotocol_getInviteCodes", "admin", {}, "status_filter",
                                                    ["active", "used", "expired"])]))
    finally:
        loop.close()
    return out[EF.PREFIX + "getInviteCodes"]


def test_an_honest_route_passes_and_a_dropped_filter_is_named():
    assert _run(_Registry(drops=False))["healthy"] is True
    row = _run(_Registry(drops=True))
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND: enum")
