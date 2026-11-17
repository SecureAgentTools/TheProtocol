"""V0664 (session-tester, session-lead seq 4287): the workflow template tools carry their switch, WORKFLOW_TEMPLATES_ENABLED.

The pair proof on nt261115x1 (V0664 cut-4, production's posture: the library off) read 6 reds that measured the switch,
not the routes: listWorkflowTemplates and listMyWorkflowTemplates failed as "expected success but got HTTP 503", and the
hygiene and range probes reported 4 BUG-FINDs whose every "server error" was the same 503 ("Workflow templates are
switched off on this registry"). The tools now carry the switch (api_tests/contracts/mcp_switches.WORKFLOW_TEMPLATES_OFF,
read from registry-config's workflow_templates_enabled): held to the switch's refusal, a 503 naming it; and the hygiene
and range probes skip a switched-off tool (NOT MEASURED, nothing sent). Red on 653824d1d: no WORKFLOW_TEMPLATES_OFF.
"""
from __future__ import annotations

import ast
import asyncio
import inspect

from agentvault_registry.api_tests.contracts import input_hygiene as H
from agentvault_registry.api_tests.contracts import mcp_contracts as C
from agentvault_registry.api_tests.contracts import mcp_switches as M
from agentvault_registry.api_tests.contracts import value_range as V

OFF_TEXT = "Error: HTTP 503: Workflow templates are switched off on this registry (WORKFLOW_TEMPLATES_ENABLED)"


def _in(config, fn):
    async def go():
        M.use_target(config)
        return await fn()
    return asyncio.run(go())


def _template_tools():
    from agentvault_registry.mcp import tools_workflow_templates as T
    return {t["name"] for t in T.WORKFLOW_TEMPLATE_PUBLIC_TOOL_SCHEMAS + T.WORKFLOW_TEMPLATE_AGENT_TOOL_SCHEMAS}


def test_every_workflow_template_tool_carries_the_switch():
    tools = _template_tools()
    assert len(tools) == 9, sorted(tools)
    assert {t for t, sw in M.SWITCHED_TOOLS.items() if sw is M.WORKFLOW_TEMPLATES_OFF} == tools
    assert "workflow_templates_enabled" in M.KEYS


def test_every_template_route_applies_the_switch_and_says_its_words():
    from agentvault_registry.routers import workflow_templates as R
    routes = [n for n in ast.parse(inspect.getsource(R)).body if isinstance(n, ast.AsyncFunctionDef)
              and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                      and d.func.attr in ("get", "post", "patch", "put", "delete") for d in n.decorator_list)]
    assert len(routes) == 13
    for fn in routes:
        called = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_require_enabled" in called, f"{fn.name} applies no switch"
    src = inspect.getsource(R._require_enabled)
    assert M.WORKFLOW_TEMPLATES_OFF.words[0] in src and "HTTP_503" in src
    assert M.WORKFLOW_TEMPLATES_OFF.status == 503


def test_the_switch_follows_the_config_and_nothing_else():
    t = "theprotocol_listWorkflowTemplates"
    assert _in({"workflow_templates_enabled": False}, lambda: _a(M.switched_off(t))) is M.WORKFLOW_TEMPLATES_OFF
    assert _in({"workflow_templates_enabled": True}, lambda: _a(M.switched_off(t))) is None
    assert _in({"staking_enabled": True}, lambda: _a(M.switched_off(t))) is None     # a target before V0664: never guessed


def test_the_judge_takes_the_switch_503_and_calls_a_2xx_a_finding():
    sw = M.WORKFLOW_TEMPLATES_OFF
    assert M.judge("theprotocol_listWorkflowTemplates", sw, 503, OFF_TEXT) == (True, None)
    ok, why = M.judge("theprotocol_listWorkflowTemplates", sw, 200, '{"items": []}')
    assert not ok and why.startswith("BUG-FIND") and "workflow_templates_enabled=false" in why
    ok, why = M.judge("theprotocol_getWorkflowTemplate", sw, 500, "Error: HTTP 500: Internal Server Error")
    assert not ok and not why.startswith("BUG-FIND")


def test_a_switched_contract_expects_the_5xx_its_switch_answers():
    base = C.get_contract("theprotocol_listWorkflowTemplates")
    held = M.refusal_contract(base, M.WORKFLOW_TEMPLATES_OFF)
    assert held.expect_status == "error_5xx" and held.expect_error_message_contains == list(M.WORKFLOW_TEMPLATES_OFF.words)
    staking = M.refusal_contract(C.get_contract("theprotocol_lockUnits"), M.STAKING_OFF)
    assert staking.expect_status == "error_4xx"       # control: a 403 switch keeps its 4xx


def _outcome(name, kind, healthy, code, ms, fail, extra, expect_status="any", skip_reason=None):
    return {"tool": name, "healthy": healthy, "status": code, "skip_reason": skip_reason, "error": fail}


def test_the_hygiene_probe_skips_a_switched_off_tool_and_sends_nothing():
    sent = []

    async def rpc(tool, args, jwt=None, timeout=30):
        sent.append(tool)
        return False, {"_text": OFF_TEXT}, 503

    outcomes = {}
    todo = [("theprotocol_getWorkflowTemplate", "1", ["template_id"], {}),
            ("theprotocol_getAgentProfile", "1", ["did"], {})]          # control: a tool no switch holds is asked

    async def go():
        M.use_target({"workflow_templates_enabled": False})
        await H.run_hygiene(lambda tier: rpc, lambda b: b, None, outcomes, _outcome, lambda *a: False, todo=todo)
    asyncio.run(go())
    row = outcomes["hygiene: getWorkflowTemplate"]
    assert row["healthy"] is False and "NOT MEASURED" in (row["skip_reason"] or "")
    assert "workflow_templates_enabled=false" in row["skip_reason"]
    assert "theprotocol_getWorkflowTemplate" not in sent and "theprotocol_getAgentProfile" in sent


def test_the_range_probe_skips_a_switched_off_tool_and_sends_nothing():
    sent = []

    async def raw(body, path="/mcp/rpc", jwt=None, timeout=30):
        sent.append(body)
        return 503, {"_text": OFF_TEXT}, None

    outcomes = {}
    todo = [("theprotocol_getWorkflowTemplateVersion", "1", {"template_id": "wtpl_x"},
             [("version", "int32+1", 2 ** 31)])]

    async def go():
        M.use_target({"workflow_templates_enabled": False})
        await V.run_range(raw, type("Bag", (), {"developer_jwt": "dev"})(), outcomes, _outcome, todo=todo)
    asyncio.run(go())
    row = outcomes["range: getWorkflowTemplateVersion"]
    assert row["healthy"] is False and "NOT MEASURED" in (row["skip_reason"] or "") and sent == []


async def _a(v):
    return v
