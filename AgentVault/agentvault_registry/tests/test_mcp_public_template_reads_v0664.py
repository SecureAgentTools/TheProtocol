"""V0664 (gwo_49787cfe12294076af80db07; found by session-volume running M6 on sbx-alpha, room seq 4110): the two PUBLIC MCP reads of the
template library, theprotocol_listWorkflowTemplates and theprotocol_getWorkflowTemplate, are tier 1: the dispatcher calls a tier-1 tool as
`tool_fn(**arguments)`, with no auth context (get_network_stats() takes none). M4 gave them an `auth` first parameter, so on every registry the
call failed with "missing a required argument: 'auth'" and neither could be used.

Held here, through the dispatcher the way the server calls each tier (never by calling the functions directly, which is how the defect passed):
* both public tools answer through `_handle_tools_call` with no token at all: the public list, and a visible template's detail;
* the dispatcher's own call of a tier-1 tool is `tool_fn(**arguments)`: neither function takes an `auth` parameter;
* a visitor reads only the public routes (the list and a template's page): never a version's files, which only the owner and buyers get;
* the agent-tier tools keep their `auth` (the dispatcher passes it).
Red on v0664/workflow-templates-mine b7b5863b6: the two calls raise.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from agentvault_registry.mcp import server, tools_workflow_templates as tw

PUBLIC = ("theprotocol_listWorkflowTemplates", "theprotocol_getWorkflowTemplate")
AGENT = ("theprotocol_getWorkflowTemplateVersion", "theprotocol_purchaseWorkflowTemplate", "theprotocol_forkWorkflowTemplate",
         "theprotocol_instantiateWorkflowTemplate", "theprotocol_createWorkflowTemplate", "theprotocol_publishWorkflowTemplateVersion")


@pytest.fixture
def seen(monkeypatch):
    """The registry's public routes, as a visitor sees them: the list, and a template's page (no files). Every path asked is kept."""
    asked = []

    async def fake_public_get(path, params=None):
        asked.append((path, dict(params or {})))
        if path.endswith("/api/v1/workflow-templates") or path == "/api/v1/workflow-templates":
            return {"items": [{"id": "wtpl_x", "title": "A kit", "pricing_model": "purchase", "price": "4"}]}
        return {"id": "wtpl_x", "title": "A kit", "structure": {"steps": []}, "versions": [{"version": 1}]}
    monkeypatch.setattr(tw, "_public_get", fake_public_get)
    return asked


def _call(name, arguments, token=None):
    return asyncio.run(server._handle_tools_call(name, dict(arguments), token))


def test_the_public_list_answers_through_the_dispatcher_with_no_token(seen):
    result, auth_ctx = _call("theprotocol_listWorkflowTemplates", {"q": "kit", "limit": 5})
    assert auth_ctx is None
    assert result["isError"] is False
    assert result["structuredContent"]["items"][0]["id"] == "wtpl_x"
    assert seen and seen[0][1].get("q") == "kit" and seen[0][1].get("limit") == 5


def test_the_public_detail_answers_through_the_dispatcher_with_no_token(seen):
    result, auth_ctx = _call("theprotocol_getWorkflowTemplate", {"template_id": "wtpl_x"})
    assert auth_ctx is None and result["isError"] is False
    assert result["structuredContent"]["id"] == "wtpl_x"


def test_a_visitor_never_reaches_a_versions_files_through_the_public_tools(seen):
    _call("theprotocol_listWorkflowTemplates", {})
    _call("theprotocol_getWorkflowTemplate", {"template_id": "wtpl_x"})
    assert seen
    for path, _ in seen:
        assert "/versions" not in path and not path.endswith("/kit"), path


def test_a_missing_template_id_is_a_refusal_not_a_crash(seen):
    result, _ = _call("theprotocol_getWorkflowTemplate", {"template_id": " "})
    assert result["isError"] is True and "template_id" in result["content"][0]["text"]


@pytest.mark.parametrize("name", PUBLIC)
def test_a_tier_one_tool_takes_no_auth_parameter(name):
    fn = server.TOOL_DISPATCH[name]
    assert "auth" not in inspect.signature(fn).parameters
    assert name not in server.TIER2_TOOLS and name not in server.AUTH_REQUIRED_TOOLS


@pytest.mark.parametrize("name", AGENT)
def test_the_agent_tier_tools_keep_their_auth(name):
    fn = server.TOOL_DISPATCH[name]
    assert next(iter(inspect.signature(fn).parameters)) == "auth"
    assert name in server.TIER2_TOOLS and name in server.AUTH_REQUIRED_TOOLS
