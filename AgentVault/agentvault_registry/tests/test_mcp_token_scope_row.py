"""§MCPTEST30 (V0529, 2026-10-01) — the operator phase asks its parent frame to refuse the operator admin's token.

A frame provisions its operators; if the two shared a token signing secret, the operator admin (developer 1 on the
operator) would authenticate at the frame as the frame's developer 1, its admin. Measured by hand on 2026-10-01, both
sandbox operators, both directions: refused (REST 401, MCP -32001). The row guards it: refused is right, answered is the
finding, no answer at all is NOT MEASURED (never read as a refusal).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F

OP = SimpleNamespace(label="sbxalphaop", parent_registry_container="sbx-alpha-registry")


def _row(monkeypatch, ok, code):
    seen = {}

    async def rpc(target, tool, args, jwt="", timeout=20):
        seen.update(container=target.a_registry_container, tool=tool, jwt=jwt)
        return ok, {}, code

    monkeypatch.setattr(F, "_mcp_rpc_call", rpc)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(F.token_scope_row(OP, "op.jwt")), seen
    finally:
        loop.close()


def test_refused_at_the_parent_is_right(monkeypatch):
    row, seen = _row(monkeypatch, False, "401")
    assert row.healthy is True and row.skip_reason is None and row.fail_reason is None
    assert seen == {"container": "sbx-alpha-registry", "tool": "theprotocol_getMyDeveloperProfile", "jwt": "op.jwt"}


def test_answered_at_the_parent_is_the_finding(monkeypatch):
    row, _ = _row(monkeypatch, True, "200")
    assert row.healthy is False and row.fail_reason.startswith("BUG-FIND: token_scope")


def test_no_answer_is_not_measured_never_a_refusal(monkeypatch):
    row, _ = _row(monkeypatch, False, "")
    assert row.healthy is False and row.skip_reason.startswith("NOT MEASURED") and row.fail_reason is None


def test_the_operator_phase_appends_the_row():
    tree = ast.parse(pathlib.Path(F.__file__).with_suffix(".py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_cloudop_mcp_sweep")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "token_scope_row"]
    assert len(calls) == 1 and [ast.unparse(a) for a in calls[0].args] == ["op", "dev_jwt"]
