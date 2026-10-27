"""§MCPTEST30 (V0549): the operator portal verifies its parent's certificate before it sends the operator's licence.

operatorPortalSelfLogs and operatorPortalSelfRestart forward to the parent frame with the operator's federation licence
in X-Federation-License. Both forwards used `verify=False`. Measured 2026-10-02 from inside every operator (the two
sandbox ones and the four production ones): each names its parent by a public theprotocol.cloud name on 443, and a
verified connection to it answers /health 200. So the licence now goes only to a server whose certificate verifies.
Read on the AST (a comment that names the old argument is not a call).
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "operator_portal_actions.py"


def _client_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "AsyncClient":
            yield node


def test_no_forward_of_the_licence_skips_the_certificate():
    tree = ast.parse(SRC.read_text())
    calls = list(_client_calls(tree))
    assert len(calls) >= 2, f"the two forwards were not found ({len(calls)} AsyncClient calls)"
    unverified = [c.lineno for c in calls
                  for kw in c.keywords if kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False]
    assert unverified == [], f"an AsyncClient with verify=False at line(s) {unverified}"


def test_the_control_finds_an_unverified_client():
    tree = ast.parse("import httpx\nasync def f():\n    async with httpx.AsyncClient(timeout=1, verify=False) as c:\n        pass\n")
    calls = list(_client_calls(tree))
    assert [kw.value.value for c in calls for kw in c.keywords if kw.arg == "verify"] == [False]
