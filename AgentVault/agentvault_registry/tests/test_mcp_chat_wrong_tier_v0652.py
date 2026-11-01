"""V0652 (agentvault2-14, 2026-11-01): what the wrong-tier auth matrix may expect a no-argument chat tool to refuse.

The matrix (test_flow_mcp_lifecycle's phase 5b) calls every tool with {} under each credential its contract expects refused
(expect_tier_rejections, else the tier's default). A tool that needs an argument answers "X is required" whatever the
credential, and the matrix counts that as refused; a chat tool that needs NONE reaches its route, so its contract has to name
the credentials the ROUTE refuses. V0651's pair proof (nt261101x1, its finding 2) went red on syncChat: the route serves a
developer key by design (dual-principal, as every chat route), while the contract (tier "2", nothing declared) expected a
developer refused. getChatUnreadCount (V0652 (w)) had the same shape.

Each chat tool that needs no argument is classified here: DUAL (its route serves a developer and an agent: only the empty
credential is refused) or DEVELOPER_ONLY (its route refuses an agent: the agent token stays among the expected refusals). A
new one fails test_every_no_argument_chat_tool_is_classified until its author decides which it is.
Red on V0651 (05441be31): syncChat's contract expects a developer refused (and getChatUnreadCount does not exist there).
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

from agentvault_registry import mcp as mcp_pkg
from agentvault_registry.api_tests.contracts.mcp_contracts import auto_tier_rejections, get_contract
from agentvault_registry.mcp import server

DUAL = {"theprotocol_listConversations", "theprotocol_syncChat", "theprotocol_getChatUnreadCount"}
DEVELOPER_ONLY = {"theprotocol_listWaitingChatApprovals"}   # agents never decide approvals: the route answers 403


def _schemas():
    """Every tool schema the MCP package declares (the *_SCHEMAS lists of its modules), by tool name."""
    out = {}
    for info in pkgutil.iter_modules(mcp_pkg.__path__):
        mod = importlib.import_module(f"{mcp_pkg.__name__}.{info.name}")
        for attr, value in vars(mod).items():
            if attr.endswith("_SCHEMAS") and isinstance(value, list):
                for t in value:
                    if isinstance(t, dict) and t.get("name"):
                        out.setdefault(t["name"], t.get("inputSchema") or t.get("input_schema") or {})
    return out


def _chat_tools():
    out = []
    for name, fn in server.TOOL_DISPATCH.items():
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        if "_chat_request(" in src:
            out.append(name)
    return out


def test_every_no_argument_chat_tool_is_classified():
    schemas = _schemas()
    chat = _chat_tools()
    assert len(chat) >= 5, f"the census found {len(chat)} chat tools: it is broken, not the contracts"
    unknown = [n for n in chat if n not in schemas]
    assert not unknown, f"chat tools with no schema to read their required arguments from: {unknown}"
    no_args = {n for n in chat if not [r for r in (schemas[n].get("required") or []) if r != "agent_jwt"]}
    assert no_args == DUAL | DEVELOPER_ONLY, {"unclassified": sorted(no_args - DUAL - DEVELOPER_ONLY),
                                             "listed but gone or now needing an argument": sorted((DUAL | DEVELOPER_ONLY) - no_args)}


def test_a_dual_tool_expects_only_the_empty_credential_refused():
    wrong = {}
    for name in sorted(DUAL):
        c = get_contract(name)
        if c is None or list(c.expect_tier_rejections) != ["empty"]:
            wrong[name] = (getattr(c, "tier", None), getattr(c, "expect_tier_rejections", None))
    assert not wrong, f"dual chat tools whose contract expects more than the empty credential refused: {wrong}"


def test_a_developer_only_tool_keeps_the_agent_token_among_the_refused():
    wrong = {}
    for name in sorted(DEVELOPER_ONLY):
        c = get_contract(name)
        refused = (list(c.expect_tier_rejections) or auto_tier_rejections(c.tier)) if c is not None else None
        if not refused or "agent_jwt" not in refused or "empty" not in refused:
            wrong[name] = refused
    assert not wrong, f"developer-only chat tools whose contract does not expect an agent refused: {wrong}"
