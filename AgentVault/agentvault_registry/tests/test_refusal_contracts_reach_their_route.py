"""§MCPTEST30 (V0550): a contract that pins a refusal must send every key its tool requires.

A refusal contract measures what the ROUTE says. If its arguments lack a key the tool's schema requires, the MCP
dispatcher refuses the call first (-32602, "missing a required argument") and the route never speaks: round 16
(2026-10-02) failed federationCliAudit that way, its contract carrying no arguments at all while the route's licence
refusal was the thing pinned. Read from the real contracts and the real served schemas; a contract that says do not call
(skip_reason) is outside it.
"""
from __future__ import annotations

from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS, McpContract
from agentvault_registry.mcp import server, server_admin

REFUSALS = ("error", "error_4xx", "error_5xx")
DISPATCHER_KEYS = ("agent_jwt", "capability_token")   # the public dispatcher pops these before it calls a tool


def _schemas():
    out = {}
    for sc in list(server.ALL_TOOL_SCHEMAS) + list(server_admin.ADMIN_TOOL_SCHEMAS):
        if isinstance(sc, dict) and "name" in sc:
            out.setdefault(sc["name"], sc)
    return out


def missing_required(name: str, contract: McpContract, schemas: dict) -> list:
    req = ((schemas.get(name) or {}).get("inputSchema") or {}).get("required") or []
    return [k for k in req if k not in (contract.arguments or {}) and k not in DISPATCHER_KEYS]


def test_every_called_refusal_contract_reaches_its_route():
    schemas = _schemas()
    assert len(schemas) > 700, f"only {len(schemas)} tool schemas read"
    pinned = {n: c for n, c in MCP_CONTRACTS.items() if c.expect_status in REFUSALS and not c.skip_reason}
    assert len(pinned) > 50, f"only {len(pinned)} refusal contracts read"
    bad = {n: missing_required(n, c, schemas) for n, c in pinned.items() if missing_required(n, c, schemas)}
    assert not bad, f"refusal contracts the dispatcher refuses before their route speaks: {bad}"


def test_the_control_finds_a_missing_key():
    schemas = _schemas()
    c = McpContract(tier="admin", expect_status="error", expect_error_message_contains=["x"])
    assert missing_required("theprotocol_federationCliAudit", c, schemas) == ["action", "cli_version", "actor_host",
                                                                               "actor_user"]
    full = MCP_CONTRACTS["theprotocol_federationCliAudit"]
    assert missing_required("theprotocol_federationCliAudit", full, schemas) == []
