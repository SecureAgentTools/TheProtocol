"""§MCPTEST30 (2026-10-01) — lifecycle_mcp_protocol_conformance against a fake MCP server.

A server that behaves as MCP asks must leave every `mcp_protocol:` row green; each defect seeded into it (a reply to a
notification, HTTP 500 for an unknown resource URI, a prompt rendered without its required argument, a task readable by
another credential, one credential's toolset selection changing another's listing, a non-admin running an admin tool)
must turn exactly its row red with a BUG-FIND. The fake keeps the real server's shapes (initialize, tools/list cursor
pages of 100, resources, prompts, completion, tasks bound to the credential, gateway mode and toolsets).
"""
from __future__ import annotations

import asyncio
import json
import urllib.parse
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L

ADMIN, DEV, SUB = "admin-jwt", "dev-jwt", "sub-jwt"
SENTINEL = "did:theprotocol:sandbox-a:sentinel"
TOOLS = [f"theprotocol_tool{i:03d}" for i in range(230)] + [
    "theprotocol_searchTools", "theprotocol_describeTools", "theprotocol_invokeTool", "theprotocol_listToolsets",
    "theprotocol_getNetworkStats", "theprotocol_getMyBalance", "theprotocol_getAgentProfile",
    "theprotocol_exportTegTransactions", "theprotocol_agentBulkExport"]
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
GATEWAY = ["theprotocol_searchTools", "theprotocol_describeTools", "theprotocol_invokeTool", "theprotocol_listToolsets",
           "theprotocol_getNetworkStats"]
WALLET = GATEWAY + ["theprotocol_getMyBalance", "theprotocol_tool001", "theprotocol_tool002"]
PROMPTS = [{"name": "fund_agent", "description": "fund", "arguments": [{"name": "agent_did", "required": True},
                                                                      {"name": "amount", "required": True}]},
           {"name": "trade_on_agora", "description": "trade", "arguments": [{"name": "ticker", "required": True}]}]


def _tool(name):
    return {"name": name, "title": name[12:], "description": f"{name} does a thing",
            "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}}


class Fake:
    def __init__(self, **defects):
        self.d = defects
        self.tasks = {}
        self.selection = {}

    def _ok(self, rid, result, code="200"):
        return code, {"jsonrpc": "2.0", "id": rid, "result": result}

    def _er(self, rid, c, msg, code="400"):
        return code, {"jsonrpc": "2.0", "id": rid, "error": {"code": c, "message": msg}}

    @staticmethod
    def _text(obj):
        return {"content": [{"type": "text", "text": json.dumps(obj)}], "isError": False}

    def listing(self, jwt, q):
        if q.get("mode") == "gateway":
            return GATEWAY
        if q.get("toolsets") == "wallet":
            return WALLET
        sel = self.selection.get(jwt) or (self.selection.get(SUB) if self.d.get("selection_leaks") and jwt else None)
        return WALLET if sel == "wallet" else TOOLS

    async def __call__(self, body, *, path="/mcp/rpc", jwt="", query="", headers=None, timeout=30):
        q = dict(urllib.parse.parse_qsl(query))
        try:
            req = json.loads(body)
        except ValueError:
            return self._er(None, -32700, "Parse error")[0], {"jsonrpc": "2.0", "id": None, "error": {"code": -32700}}, ""
        if isinstance(req, list):
            c, p = self._er(None, -32600, "Invalid Request")
            return c, p, json.dumps(p)
        m, rid, params = req.get("method"), req.get("id"), req.get("params") or {}
        if not m:
            c, p = self._er(None, -32600, "Invalid Request")
            return c, p, json.dumps(p)
        if m.startswith("notifications/"):
            if path == "/mcp/admin" and m != "notifications/initialized" and self.d.get("admin_notification_error"):
                txt = 'event: message\ndata: {"jsonrpc":"2.0","id":null,"error":{"code":-32601}}'
                return "200", None, txt
            if self.d.get("notification_reply") and path == "/mcp":
                return "200", {"jsonrpc": "2.0", "id": None, "result": {}}, '{"jsonrpc":"2.0","id":null,"result":{}}'
            return "202", None, ""
        c, p = self.dispatch(m, rid, params, jwt, q, path)
        return c, p, json.dumps(p)[:4000]

    def dispatch(self, m, rid, params, jwt, q, path):
        if q.get("mode") not in (None, "gateway") or q.get("toolsets") not in (None, "wallet"):
            return self._er(rid, -32602, "Invalid params")
        if m == "initialize":
            caps = {"tools": {}, "resources": {}, "tasks": {}} if "admin" in path else {"tools": {}, "resources": {}, "prompts": {}, "tasks": {}}
            # V0649's rule (mcp/protocol_version.py): a supported version is echoed, anything else gets the latest;
            # the seeded defect is V0648's own constant whatever was asked
            asked = params.get("protocolVersion")
            pv = asked if asked in VERSIONS and not self.d.get("constant_version") else VERSIONS[0]
            if self.d.get("echo_anything"):
                pv = asked
            return self._ok(rid, {"protocolVersion": pv, "capabilities": caps, "serverInfo": {"name": "TP", "version": "1"}})
        if m == "ping":
            return self._ok(rid, {})
        if m == "tools/list":
            if "admin" in path:
                return self._ok(rid, {"tools": [_tool(f"theprotocol_admin{i}") for i in range(5)]})
            names = self.listing(jwt, q)
            if "cursor" in params:
                try:
                    start = int(params["cursor"])
                    assert start >= 0
                except (ValueError, AssertionError):
                    return self._er(rid, -32602, "bad cursor")
                page = names[start:start + 100]
                out = {"tools": [_tool(n) for n in page]}
                if start + 100 < len(names):
                    out["nextCursor"] = str(start + 100)
                return self._ok(rid, out)
            return self._ok(rid, {"tools": [_tool(n) for n in names]})
        if m == "resources/list":
            return self._ok(rid, {"resources": [{"uri": "theprotocol://registry/card", "name": "card", "mimeType": "application/json"}]})
        if m == "resources/templates/list":
            return self._ok(rid, {"resourceTemplates": [{"uriTemplate": "theprotocol://agent/{did}/card", "name": "a"}]})
        if m == "resources/read":
            uri = params.get("uri") or ""
            if uri == "theprotocol://registry/card":
                return self._ok(rid, {"contents": [{"uri": uri, "text": json.dumps({"identity": {}})}]})
            if uri.startswith("theprotocol://agent/"):
                did = uri[len("theprotocol://agent/"):-len("/card")]
                return self._ok(rid, {"contents": [{"uri": uri, "text": json.dumps({"did": did})}]})
            return self._er(rid, -32002, f"unknown resource URI: {uri}", code="500" if self.d.get("resource_500") else "404")
        if m == "prompts/list":
            return self._ok(rid, {"prompts": PROMPTS})
        if m == "prompts/get":
            pr = next((x for x in PROMPTS if x["name"] == params.get("name")), None)
            if not pr:
                return self._er(rid, -32602, "Unknown prompt")
            args = params.get("arguments") or {}
            missing = [a["name"] for a in pr["arguments"] if a.get("required") and a["name"] not in args]
            if missing and not self.d.get("prompt_renders_without_args"):
                return self._er(rid, -32602, f"missing {missing}")
            return self._ok(rid, {"messages": [{"role": "user", "content": {"type": "text", "text": " ".join(str(v) for v in args.values()) or "x"}}]})
        if m == "completion/complete":
            return self._ok(rid, {"completion": {"values": ["MCPT"], "total": 1, "hasMore": False}})
        if m.startswith("tasks/"):
            return self.tasks_api(m, rid, params, jwt)
        if m == "tools/call":
            return self.call(rid, params, jwt, path)
        return self._er(rid, -32601, f"Method not found: {m}", code="404")

    def tasks_api(self, m, rid, params, jwt):
        if m == "tasks/list":
            return self._ok(rid, {"tasks": [{"taskId": t} for t, v in self.tasks.items() if v["owner"] == jwt]})
        t = self.tasks.get(params.get("taskId"))
        if not t or (t["owner"] != jwt and not self.d.get("task_readable_by_others")):
            return self._er(rid, -32602, "Task not found")
        if m == "tasks/get":
            return self._ok(rid, {"taskId": params["taskId"], "status": t["status"]})
        if m == "tasks/result":
            return self._ok(rid, dict(t["result"], _meta={"io.modelcontextprotocol/related-task": {"taskId": params["taskId"]}}))
        if m == "tasks/cancel":
            return self._er(rid, -32602, "already in terminal status")
        return self._er(rid, -32601, "no")

    def call(self, rid, params, jwt, path):
        name, args = params.get("name"), params.get("arguments") or {}
        if "admin" in path:
            if jwt != ADMIN and not self.d.get("admin_gate_open"):
                return self._er(rid, -32001, "requires admin auth", code="401")
            return self._ok(rid, self._text({"dashboard": 1}))
        if params.get("task") is not None:
            if name not in ("theprotocol_exportTegTransactions", "theprotocol_agentBulkExport"):
                return self._er(rid, -32601, "does not support task-augmented execution", code="404")
            tid = f"t{len(self.tasks)}"
            if name == "theprotocol_agentBulkExport":   # the real shape: 200, a refused agent listed under errors
                dids = args.get("agent_dids") or []
                res = self._text({"successful_exports": len(dids), "agents": [{"agent": {"did": d}} for d in dids], "errors": []}
                                 if self.d.get("foreign_export_completes") else
                                 {"successful_exports": 0, "agents": [], "errors": [{"agent_did": d, "error": "Agent not found"} for d in dids]})
            else:
                res = self._text({"transactions": []})
            self.tasks[tid] = {"owner": jwt, "status": "completed", "result": res}
            return self._ok(rid, {"task": {"taskId": tid, "status": "working", "ttl": 60000}})
        if name not in TOOLS + ["theprotocol_enableToolset", "theprotocol_disableToolset"]:
            return self._er(rid, -32601, "Tool not found", code="404")
        if name == "theprotocol_getAgentProfile" and "agent_did" not in args:
            return self._er(rid, -32602, "missing agent_did")
        if name == "theprotocol_searchTools":
            return self._ok(rid, self._text({"results": [{"name": "theprotocol_getMyBalance"}]}))
        if name == "theprotocol_describeTools":
            return self._ok(rid, self._text({"tools": [_tool(n) for n in args.get("names") or []]}))
        if name == "theprotocol_invokeTool":
            if args.get("name") == "theprotocol_invokeTool":
                return self._er(rid, -32602, "invokeTool cannot invoke itself")
            return self._ok(rid, self._text({"agents": 3, "registries": 2}))
        if name == "theprotocol_getNetworkStats":
            return self._ok(rid, self._text({"agents": 3, "registries": 2}))
        if name == "theprotocol_enableToolset":
            self.selection[jwt] = "wallet"
            return self._ok(rid, self._text({"enabled_toolsets": ["wallet"], "session_scope": "24h"}))
        if name == "theprotocol_disableToolset":
            self.selection.pop(jwt, None)
            return self._ok(rid, self._text({"enabled_toolsets": [], "session_scope": "24h"}))
        return self._ok(rid, self._text({"ok": True}))


def _run(fake):
    async def mint(role):
        return {"email": f"{role}@x", "password": "p", "access_token": SUB}

    async def rpc(tool, args, jwt="", timeout=20):
        return True, {}, "200"

    async def login(email, password):
        return "200", {"access_token": SUB}
    bag = SimpleNamespace(rpc_raw=fake, mint_throwaway=mint, developer_jwt=DEV, admin_jwt=ADMIN, sentinel_did=SENTINEL,
                          dev_login=login)
    outcomes = {}

    async def go():
        orig = L.asyncio.sleep

        async def fast(_s):
            await orig(0)
        L.asyncio.sleep = fast
        try:
            await L.lifecycle_mcp_protocol_conformance(rpc, None, bag, outcomes)
        finally:
            L.asyncio.sleep = orig
    asyncio.run(go())
    return outcomes


def _red(outcomes):
    return {k[len("mcp_protocol: "):]: v["fail_reason"] for k, v in outcomes.items() if not v["healthy"]}


def test_a_conformant_server_leaves_every_row_green():
    out = _run(Fake())
    assert len(out) >= 20, sorted(out)
    assert _red(out) == {}, _red(out)
    assert all(k.startswith("mcp_protocol: ") for k in out)


@pytest.mark.parametrize("defect,row,needle", [
    ("notification_reply", "notifications: public", "BUG-FIND (conformance): a notification was answered HTTP 200"),
    ("admin_notification_error", "notifications: admin cancelled", "BUG-FIND (conformance): a notification was answered HTTP 200"),
    ("resource_500", "resources: unknown uri", "BUG-FIND (conformance): an unknown resource URI answers HTTP 500"),
    ("prompt_renders_without_args", "prompts: missing required argument", "BUG-FIND (conformance): prompts/get"),
    ("task_readable_by_others", "tasks: another credential cannot read it", "BUG-FIND: a task made by one credential"),
    ("foreign_export_completes", "tasks: owner rules hold", "BUG-FIND: an owner-only export of ANOTHER developer's agent was exported"),
    ("selection_leaks", "toolsets: per-credential selection", "BUG-FIND: one credential's toolset selection"),
    ("admin_gate_open", "admin: surface and gate", "BUG-FIND: a NON-admin credential ran an admin tool"),
    ("constant_version", "initialize: version negotiation",
     "BUG-FIND (conformance): public initialize asked for 2025-06-18 and answered '2025-11-25'"),
    ("echo_anything", "initialize: version negotiation",
     "BUG-FIND (conformance): public initialize asked for 1999-01-01 (no server supports it) and answered '1999-01-01'"),
])
def test_each_seeded_defect_reddens_exactly_its_row(defect, row, needle):
    red = _red(_run(Fake(**{defect: True})))
    assert row in red and needle in red[row], red
    assert set(red) == {row}, f"{defect} reddened more than its own row: {sorted(red)}"


def test_without_a_raw_transport_the_lifecycle_says_not_measured():
    out = {}
    asyncio.run(L.lifecycle_mcp_protocol_conformance(None, None, SimpleNamespace(), out))
    assert list(out) == ["mcp_protocol: conformance"] and out["mcp_protocol: conformance"]["skip_reason"].startswith("NOT MEASURED")


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
