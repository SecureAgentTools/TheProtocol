"""§BAFIN (2026-10-01): every public fiat read that names a euro price or sells the backer tiers answers 503 while the
lane is off (FIAT_ONRAMP_ENABLED is not "true"), exactly like /fiat/tiers has since 2026-07-31.

Measured on EU that day with the lane off: /fiat/tiers 503, but POST /fiat/quote answered "10.00 EUR = 20000" and
/fiat/stats/public answered "founder_slots_remaining: 100", both without login. Structural (the AST of each route), because
importing the router needs the whole app; the check is that the kill-switch test runs before anything is computed.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "fiat_onramp.py"
GATED = {"get_tiers": "/tiers", "quote_fiat": "/quote", "get_public_stats": "/stats/public"}


def _fn(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    assert len(fns) == 1, (name, len(fns))
    return fns[0]


@pytest.mark.parametrize("name", sorted(GATED))
def test_the_kill_switch_is_the_first_thing_each_public_read_checks(name):
    fn = _fn(name)
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]  # skip docstring
    first = body[0]
    assert isinstance(first, ast.If), f"{name}: the first statement must be the lane check, got {ast.unparse(first)[:80]}"
    assert ast.unparse(first.test) == "not _fiat_enabled()", ast.unparse(first.test)
    raised = [n for n in ast.walk(first) if isinstance(n, ast.Raise)]
    assert raised and "HTTP_503_SERVICE_UNAVAILABLE" in ast.unparse(raised[0]), f"{name} must refuse with 503"


def test_the_lane_is_off_unless_explicitly_true(monkeypatch):
    """The flag's default is OFF (the opposite of the staking switches): a node that sets nothing sells nothing."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_fiat_enabled"]
    assert len(fn) == 1
    src = ast.unparse(fn[0])
    assert "'FIAT_ONRAMP_ENABLED', 'false'" in src and "== 'true'" in src, src
