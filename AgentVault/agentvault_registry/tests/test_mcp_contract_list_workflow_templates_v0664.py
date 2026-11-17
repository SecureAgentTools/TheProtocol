"""V0664 (session-tester): listWorkflowTemplates holds a contract of its own.

The pair proof on nt261115x2 (V0664 cut-5, the library on for the pair, session-lead seq 4287) read one lifecycle red:
"theprotocol_listWorkflowTemplates: contract gap: no expect_keys AND no outputSchema.required". On cut-4 the switch held
the tool to its refusal; with the library on, it reached its success path on a default contract that names no key. The
route (GET /api/v1/workflow-templates) is public and answers {"items": [...]} (services.workflow_templates.Library.list).
Red on 7a0f0269b: no explicit contract. And (session-lead seq 4308) every other template tool holds a contract of its own
too: on the pair they read "default contract: tool has required params", NOT MEASURED; each is now held to the route's
refusal for a template that does not exist, which writes nothing.
"""
from __future__ import annotations

from agentvault_registry.api_tests.contracts import mcp_contracts as C
from agentvault_registry.api_tests.contracts import mcp_switches as M


def test_list_workflow_templates_has_an_explicit_public_contract():
    c = C.MCP_CONTRACTS.get("theprotocol_listWorkflowTemplates")
    assert c is not None, "no explicit contract"
    assert c.tier == "1" and c.expect_status == "success" and c.expect_keys == ["items"]


def test_the_switch_still_holds_it_where_the_library_is_off():
    held = M.refusal_contract(C.get_contract("theprotocol_listWorkflowTemplates"), M.WORKFLOW_TEMPLATES_OFF)
    assert held.expect_status == "error_5xx"


def test_every_template_tool_holds_a_contract_of_its_own():
    from agentvault_registry.api_tests.contracts.mcp_switches import SWITCHED_TOOLS
    tools = {t for t, sw in SWITCHED_TOOLS.items() if sw is M.WORKFLOW_TEMPLATES_OFF}
    assert len(tools) == 9
    missing = sorted(t for t in tools if t not in C.MCP_CONTRACTS)
    assert missing == [], missing


def test_the_refusals_name_the_routes_sentences():
    import inspect
    from agentvault_registry.services import workflow_templates as W
    src = inspect.getsource(W)
    for t in ("theprotocol_getWorkflowTemplate", "theprotocol_getWorkflowTemplateVersion",
              "theprotocol_purchaseWorkflowTemplate", "theprotocol_forkWorkflowTemplate",
              "theprotocol_instantiateWorkflowTemplate", "theprotocol_publishWorkflowTemplateVersion",
              "theprotocol_createWorkflowTemplate"):
        c = C.MCP_CONTRACTS[t]
        assert c.expect_status == "error_4xx" and c.success_path_unmeasured
        for words in c.expect_error_message_contains:
            assert words in src, (t, words)
