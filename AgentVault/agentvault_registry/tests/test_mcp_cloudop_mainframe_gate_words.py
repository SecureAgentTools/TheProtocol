"""§MCPTEST30 (V0639): the operator sweep reads the mainframe gate's refusal by its words, at 503 today and at 404 after.

core/mainframe_gate.require_mainframe_only refuses every mainframe-only route on an operator, and the operator sweep
counts that refusal as the operator's contract met ("refused by construction"), keyed on the gate's sentence.
agentvault2-d6 means to answer it 404 instead of 503 (V0640, agentvault2-aa's and agentvault2-66's vote). Pinned: the
gate's own words (raised here, never copied) carry a phrase of both of the sweep's lists, and the sweep's own gating rule
(its expression, evaluated as written) reads a 404 that carries them as the gate's while a bare 404 stays a failure. A
change of status keeps the rows; a change of words fails here first.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.core import mainframe_gate as G


def _sweep():
    return ast.parse("class X:\n" + inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep))


def _assigned(name):
    found = [n.value for n in ast.walk(_sweep()) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(found) == 1, name
    return found[0]


def _is_gated(status, blob, tool="theprotocol_noSuchTool"):
    rule = compile(ast.Expression(body=_assigned("_is_gated")), "<_is_gated>", "eval")
    return eval(rule, {}, {"o": SimpleNamespace(status_code=status, tool_name=tool),
                           "_marker_hit": any(m in blob for m in F.CLOUDOP_GATE_MARKERS),
                           "_FLAG_GATED_CLOUDOP_TOOLS": set()})


@pytest.fixture
def refusal(monkeypatch):
    monkeypatch.setattr(G, "is_mainframe", lambda: False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(G.require_mainframe_only())
    return e.value


def test_the_gates_words_are_a_refusal_by_construction(refusal):
    blob = str(refusal.detail).lower()
    assert any(m in blob for m in F.CLOUDOP_GATE_MARKERS)
    assert any(m in blob for m in F.CLOUDOP_BY_CONSTRUCTION_MARKERS)


def test_the_gates_status_is_read_as_the_gate(refusal):
    assert _is_gated(refusal.status_code, f"error: http {refusal.status_code}: {refusal.detail}".lower())


def test_a_404_with_the_gates_words_is_the_gate_and_a_bare_404_is_not(refusal):
    assert _is_gated(404, f"error: http 404: {refusal.detail}".lower())
    assert not _is_gated(404, "error: http 404: not found")
    assert _is_gated(503, "error: http 503")


def test_the_code_word_alone_is_read_as_the_gate():
    """§MCPTEST30 (V0640): D6-820 answers `mainframe_only: <the sentence>`; the code word is the answer's stable part,
    so a reworded sentence keeps the rows (a bare 404 still does not)."""
    blob = "error: http 404: mainframe_only: this registry cannot do that".lower()
    assert _is_gated(404, blob)
    assert any(m in blob for m in F.CLOUDOP_BY_CONSTRUCTION_MARKERS)
    assert not _is_gated(404, "error: http 404: not found")
