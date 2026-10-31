"""§MCPTEST30 (tester batch 2 item 1, agentvault2-d3, Guild order gwo_e3bad842b1a5943022b01d40): two answers judged by
nothing become refusal rows held to their rule's sentence.

requestSelfRevocation (lifecycle_self_revocation_safe) and rotateFederationLicenseSelf (lifecycle_misc_safe) were probed
under their own names with any answer accepted, and the router said so on the sbx-alpha nightly of 2026-10-31 (run
60e40b9afff04e7c): "lifecycle recorded a 401/403 as healthy ... the success path was not measured". Each is now a
`refusal:` row that passes only on its rule's status and words: 403 "You are not an active operator." (the runner is the
frame's admin, never a federation operator) and 401 "Federation license not recognised" (a key that matches no licence).
RED on the code before: the rows are filed under the tools' own names and pass on any answer.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag

SELF_REVOKE = "theprotocol_requestSelfRevocation"
ROTATE_SELF = "theprotocol_rotateFederationLicenseSelf"


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                   "structuredContent": obj}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


def _run_self_revocation(answer: Tuple[bool, Any, str]) -> Dict[str, dict]:
    calls: List[str] = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append(tool)
        assert tool == SELF_REVOKE and "do NOT actually revoke" in args["reason"]
        ok, obj, code = answer
        return ok, _body(obj), code
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    out: Dict[str, dict] = {}
    asyncio.run(L.lifecycle_self_revocation_safe(rpc, _parse, bag, out))
    assert calls == [SELF_REVOKE]
    return out


ROW = "refusal: requestSelfRevocation a developer that is no federation operator"


def test_the_rules_refusal_is_a_refusal_row_and_the_tools_name_is_left_to_its_contract():
    out = _run_self_revocation((False, {"error": "HTTP 403: You are not an active operator."}, "403"))
    assert SELF_REVOKE not in out, "the tool's own row is its contract's (skip: not probed), never an any-answer"
    assert out[ROW]["healthy"] and not out[ROW].get("fail_reason"), out[ROW]


@pytest.mark.parametrize("answer,needle", [
    ((True, {"status": "requested"}, "200"), ""),
    ((False, {"error": "HTTP 403: Admin access required"}, "403"), "not for the rule under test"),
    ((False, {"error": "HTTP 401: Could not validate credentials"}, "401"), "not one of [403]"),
])
def test_anything_else_is_red(answer, needle):
    out = _run_self_revocation(answer)
    assert not out[ROW]["healthy"] and needle in str(out[ROW].get("fail_reason")), out[ROW]


def test_the_licence_rotation_probe_is_held_to_its_sentence():
    src = inspect.getsource(L.lifecycle_misc_safe)
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and any(isinstance(a, ast.Constant) and a.value == ROTATE_SELF for a in n.args)]
    assert calls, "the probe left misc_safe"
    for c in calls:
        name = c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
        kw = {k.arg: k.value for k in c.keywords}
        assert name == "refusal_step", f"{ROTATE_SELF} is probed by {name}, not a refusal row"
        assert ast.literal_eval(kw["codes"]) == (401,) and ast.literal_eval(kw["text"]) == "not recognised"


def test_no_lifecycle_accepts_any_answer_from_either_tool_any_more():
    tree = ast.parse(inspect.getsource(L))
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_exec_step"):
            continue
        tools = {a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        if tools & {SELF_REVOKE, ROTATE_SELF}:
            kw = {k.arg: k.value for k in n.keywords}
            assert not (isinstance(kw.get("expect_status"), ast.Constant) and kw["expect_status"].value == "any"), \
                tools


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
