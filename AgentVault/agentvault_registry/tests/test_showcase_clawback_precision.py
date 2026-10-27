"""§MONEY-R29 — a money leg must not lose precision on the way out, and must carry its key.

`background_tasks/showcase_visitor_sweeper.py::_clawback` posted `float(amount)` for a value
read as `Decimal(str(...))`. The TEG declares `amount: Decimal` on that route, and the PROVEN
escrow rail (`services/escrow.py::escrow_deposit`) posts `str(amount)` to the SAME endpoint —
so `float()` was the outlier, and the same truncation class as the velocity / local-trust
columns closed in §VITALS.

It also sent no `Idempotency-Key`, although the route accepts one and the reference
(`showcase-sweep-{did tail}`) was already deterministic. Escrow doctrine: every money leg
carries its durable key.
"""
from __future__ import annotations

import ast
import pathlib

_SRC = (
    pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
    / "background_tasks" / "showcase_visitor_sweeper.py"
)


def _clawback_fn(tree: ast.AST) -> ast.AsyncFunctionDef:
    for n in ast.walk(tree):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_clawback":
            return n
    raise AssertionError("_clawback not found — did the sweeper get renamed?")


def test_clawback_amount_is_not_passed_through_float():
    fn = _clawback_fn(ast.parse(_SRC.read_text()))
    bad = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"
    ]
    assert not bad, (
        f"float() applied inside the clawback at {bad} — an 18-decimal Decimal is truncated "
        f"on its way into a money leg"
    )


def test_clawback_sends_a_decimal_safe_amount():
    fn = _clawback_fn(ast.parse(_SRC.read_text()))
    strs = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str"
    ]
    assert strs, "the clawback must serialise the amount with str(), matching services/escrow.py"


def test_clawback_carries_an_idempotency_key():
    fn = _clawback_fn(ast.parse(_SRC.read_text()))
    keys = [
        n.value for n in ast.walk(fn)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert "Idempotency-Key" in keys, (
        "every money leg carries its durable key (services/escrow.py); this route accepts one "
        "and the reference is already deterministic per DID"
    )
