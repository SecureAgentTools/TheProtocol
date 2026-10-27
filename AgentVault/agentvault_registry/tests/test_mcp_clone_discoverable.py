"""§MCPTEST30 (V0534) — the clone lifecycle asks discoverAgents for the name it gave the clone: the clone must be found.

An import made its card with the DID only in its JSON (agent_cards.agent_did NULL), so a search by name found no card for
the clone, every run, while cloneAgent answered success (sbx-alpha: 296 such cards). The lifecycle now names that as a
BUG-FIND on cloneAgent's row; a search that does not answer measures nothing. Drives the REAL lifecycle and `_exec_step`
with a fake RPC layer; the control (the clone missing) must fail the row.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.contracts import mcp_lifecycles as ml  # noqa: E402
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    _parse_rpc_result,
)

CLONE = "did:theprotocol:the-clone"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _env(data, is_error=False):
    text = data if isinstance(data, str) else json.dumps(data)
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}


def _run(search):
    """search: 'found' (the clone listed under its name), 'missing' (another agent only), 'error' (no answer)."""
    asked = {}

    async def rpc(tool, args, jwt="", timeout=15):
        if tool == "theprotocol_cloneAgent":
            asked["name"] = args["new_name"]
            return True, _env({"success": True, "agent_did": CLONE}), "200"
        if tool == "theprotocol_discoverAgents":
            asked["query"] = args.get("query")
            if search == "error":
                return False, _env("Error: discover endpoint returned HTTP 503", is_error=True), "503"
            agents = [{"did": "did:theprotocol:someone-else", "name": "x"}]
            if search == "found":
                agents.append({"did": CLONE, "name": asked["name"]})
            return True, _env({"agents": agents, "total": len(agents)}), "200"
        if tool == "theprotocol_getMyAgents":
            return True, _env({"agents": []}), "200"
        return True, _env({}), "200"

    outcomes = {}
    bag = SimpleNamespace(developer_jwt="dev-jwt", sentinel_did="did:theprotocol:sentinel")
    asyncio.run(ml.lifecycle_agent_clone_export_delete(rpc, _parse_rpc_result, bag, outcomes))
    return outcomes["theprotocol_cloneAgent"], asked


def test_a_clone_found_by_its_name_keeps_its_row_healthy():
    row, asked = _run("found")
    assert asked["query"] == asked["name"], "the search asks for the name the clone was given"
    assert row["healthy"] is True and not (row.get("fail_reason") or ""), row


def test_a_clone_missing_from_a_search_for_its_name_is_a_bug_find():
    row, _ = _run("missing")
    assert row["healthy"] is False and "BUG-FIND" in row["fail_reason"], row
    assert "not found by the name it was given" in row["fail_reason"] and "agent_cards.agent_did" in row["fail_reason"]


def test_a_search_that_did_not_answer_measures_nothing():
    row, _ = _run("error")
    assert row["healthy"] is True and "BUG-FIND" not in (row.get("fail_reason") or ""), row
